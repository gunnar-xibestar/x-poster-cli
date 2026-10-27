import json, threading, urllib.request, stat
import pytest
from xbot import oauth2
from xbot.app import XBotApp, PostCard
from xbot.xapi import XError
from tests.test_search import S
from tests.test_card_open import rich_post


@pytest.fixture
def cfgdir(tmp_path, monkeypatch):
    import xbot.config as C
    monkeypatch.setattr(C, "CONFIG_DIR", tmp_path)
    return tmp_path


class RX:
    def __init__(self, err=None): self.calls = []; self.err = err
    def like(self, tid, bearer=None):
        self.calls.append((tid, bearer))
        if self.err: raise XError(self.err)
        return True


def mkbot(mk, rx):
    b = mk(xonly=True, search=[rich_post(5)], **S()); b.tick()
    b.real_x = rx
    return b


def test_like_oauth1(mk, cfgdir):
    rx = RX(); b = mkbot(mk, rx)
    ok, msg = b.like_post(1)
    assert ok and rx.calls == [("5", None)] and "[LIVE] liked #1" in b.log.path.read_text()


def test_like_with_oauth2_token_and_scope_check(mk, cfgdir):
    rx = RX(); b = mkbot(mk, rx)
    oauth2.save_tokens({"access_token": "AT-fake-123456", "refresh_token": "RT-fake-123456", "expires_in": 7200,
                        "scope": "tweet.read users.read like.write offline.access"})
    assert stat.S_IMODE((cfgdir / "tokens.json").stat().st_mode) == 0o600
    ok, _ = b.like_post(1)
    assert ok and rx.calls == [("5", "AT-fake-123456")]
    assert "AT-fake-123456" not in b.log.path.read_text() and "AT-fake" not in __import__("xbot.secure", fromlist=["x"]).redact("t=AT-fake-123456")
    oauth2.save_tokens({"access_token": "AT2-fake-123456", "expires_in": 7200, "scope": "tweet.read users.read"})
    ok, msg = b.like_post(1)
    assert not ok and "like.write" in msg and "xbot login" in msg and len(rx.calls) == 1


@pytest.mark.parametrize("err,want", [("X API 429 rate limited", "429"), ("X API 403 forbidden", "Read and write"),
                                      ("X API 500 error", "500")])
async def test_l_rolls_back_and_notifies_on_error(mk, cfgdir, err, want):
    rx = RX(err); b = mkbot(mk, rx)
    notes, opened = [], []
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 40)) as pilot:
        b.opener = lambda url, done: opened.append(url)
        app.notify = lambda m, **k: notes.append(m)
        app.action_show_post(1); await pilot.pause()
        card = app.screen
        await pilot.press("l"); await pilot.pause(0.3)
        assert b.state.liked == [] and any(want in n for n in notes) and opened == []
        assert card.heart_frames_shown  # heart still plays
        rx.err = None
        await pilot.press("l"); await pilot.pause(0.3); await pilot.press("l"); await pilot.pause(0.3)
        assert b.state.liked == ["5"] and len(rx.calls) == 2  # retried after rollback, then once only
        b.stopped = True


def test_refresh_when_expired(cfgdir):
    oauth2.save_tokens({"access_token": "fake-fake-fake-old", "refresh_token": "fake-fake-fake-rt", "expires_in": 0,
                        "scope": "like.write offline.access"})
    sent = []
    class R:
        status_code = 200
        def json(self): return {"access_token": "fake-fake-fake-new", "expires_in": 7200, "token_type": "bearer"}
    t = oauth2.refresh_if_needed(post=lambda url, **k: (sent.append((url, k)), R())[1], client_id="cid")
    assert t["access_token"] == "fake-fake-fake-new" and t["refresh_token"] == "fake-fake-fake-rt" and "like.write" in t["scope"]
    assert sent[0][0] == oauth2.TOKEN_URL and sent[0][1]["data"]["grant_type"] == "refresh_token"
    assert oauth2.load_tokens()["access_token"] == "fake-fake-fake-new"


def test_login_pkce_flow_with_mocked_token_endpoint(cfgdir):
    seen = {}
    def open_url(url):
        from urllib.parse import urlsplit, parse_qs
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        seen.update(q)
        urllib.request.urlopen(f"{oauth2.REDIRECT.replace('8765', str(port))}?code=CODE123&state={q['state']}", timeout=5).read()
    posted = []
    class R:
        status_code = 200
        def json(self): return {"access_token": "acc-tok-999999", "refresh_token": "ref-tok-999999", "expires_in": 7200,
                                "scope": oauth2.SCOPES}
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    out = []
    rc = oauth2.login("cid-1", None, open_url=open_url, post=lambda url, **k: (posted.append(k), R())[1], out=out.append,
                      timeout=10, port=port)
    assert rc == 0 and seen["code_challenge_method"] == "S256" and seen["scope"] == oauth2.SCOPES
    assert posted[0]["data"]["code"] == "CODE123" and posted[0]["data"]["code_verifier"] and "auth" not in posted[0]
    assert oauth2.load_tokens()["refresh_token"] == "ref-tok-999999"
    assert not any("acc-tok" in o for o in out)


def test_login_without_client_id_prints_steps(cfgdir, monkeypatch):
    monkeypatch.delenv("X_CLIENT_ID", raising=False)
    out = []
    assert oauth2.login(out=out.append) == 2 and "Read and write" in out[0] and oauth2.REDIRECT in out[0]
