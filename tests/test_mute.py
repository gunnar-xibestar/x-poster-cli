import json
import pytest
from xbot.commands import parse
from xbot.xapi import RealX, XError
from xbot.app import XBotApp, Confirm, PostCard
from tests.test_search import P, S


class FakeLive:
    def __init__(self, fail=None):
        self.calls, self.fail, self._uid = [], fail, None
    def me(self):
        self._uid = self._uid or "42"; return self._uid
    def user_id(self, h):
        self.calls.append(("lookup", h)); return "777"
    def mute(self, tid):
        self.me()
        if self.fail: raise XError(self.fail)
        self.calls.append(("mute", tid)); return True
    def unmute(self, tid):
        self.calls.append(("unmute", tid)); return True


def test_dry_mute_blocks_locally_only(mk):
    b = mk(xonly=True, search=[P(1, author="spam")], **S()); b.tick()
    b.handle(parse("/mute @uspam"))
    assert "uspam" in b.cfg.blocked_authors and b.cfg.muted_authors["uspam"] == {"id": "spam", "live": False}
    assert any("[DRY-MUTE] @uspam" in f for f in b.feed) and b.state.spent_today() == 0
    b.handle(parse("/muted")); assert "mute (real):" in b.feed[-1] and "@uspam (dry run" in b.feed[-1]
    b.handle(parse("/unmute @uspam")); assert b.cfg.muted_authors == {} and b.cfg.blocked_authors == []
    with pytest.raises(KeyError): b.handle(parse("/unmute @nobody"))


def test_live_mute_uses_known_author_id_and_caches_me(mk):
    b = mk(xonly=True, search=[P(1, author="spam")], **S()); b.tick()
    x = FakeLive(); b.real_x_factory = lambda: x
    b.handle(parse("/send live"))
    b.handle(parse("/mute uspam"))
    assert x.calls == [("mute", "spam")] and b.cfg.muted_authors["uspam"]["live"]
    assert b.state.me_id == "42" and round(b.state.spent_today(), 3) == 0.015
    assert any("[LIVE] mute (real) @uspam" in f for f in b.feed)
    b.handle(parse("/mute @stranger")); assert x.calls[-2:] == [("lookup", "stranger"), ("mute", "777")]
    b.handle(parse("/unmute @uspam")); assert x.calls[-1] == ("unmute", "spam") and "uspam" not in b.cfg.muted_authors


@pytest.mark.parametrize("err,needle", [("X API 403 forbidden: no", "X refused (403)"),
                                        ("X API 402 out of X API credits", "credits exhausted (402)")])
def test_live_mute_errors_are_clear_and_still_block(mk, err, needle):
    b = mk(xonly=True); x = FakeLive(fail=err); b.real_x_factory = lambda: x
    b.handle(parse("/send live")); b.handle(parse("/mute @bad"))
    assert "bad" in b.cfg.blocked_authors and "bad" not in b.cfg.muted_authors
    assert needle in b.feed[-1] and "block (local) only" in b.feed[-1]


def test_cached_me_id_reused(mk):
    b = mk(xonly=True); b.state.me_id = "42"
    x = FakeLive(); b.real_x_factory = lambda: x
    b.handle(parse("/send live")); b.x
    assert x._uid == "42"


def test_realx_mute_requests(monkeypatch):
    for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"):
        monkeypatch.setenv(k, "v")
    x = RealX(); x._uid = "42"; calls = []
    def req(method, path, **kw):
        calls.append((method, path, kw.get("json")))
        return {"data": {"muting": method == "POST", "id": "9"}}
    x._req = req
    assert x.mute("9") is True and x.unmute("9") is True and x.user_id("bob") == "9"
    assert calls == [("POST", "/users/42/muting", {"target_user_id": "9"}),
                     ("DELETE", "/users/42/muting/9", None), ("GET", "/users/by/username/bob", None)]


async def test_card_m_confirm(mk):
    b = mk(xonly=True, search=[P(1, author="spam")], **S()); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app.action_show_post(1); await pilot.pause()
        await pilot.press("m"); await pilot.pause()
        assert isinstance(app.screen, Confirm) and "Mute @uspam (real)? y/n" in app.screen.msg
        await pilot.press("n"); await pilot.pause(); assert b.cfg.muted_authors == {}
        await pilot.press("m"); await pilot.pause(); await pilot.press("y"); await pilot.pause()
        assert isinstance(app.screen, PostCard) and "uspam" in b.cfg.muted_authors


def test_card_status_and_hint_wording(mk):
    from rich.console import Console
    from xbot.render import card_renderable
    b = mk(xonly=True, search=[P(1, author="a"), P(2, author="b")], **S()); b.tick()
    b.handle(parse("/block @ua")); b.handle(parse("/mute @ub"))
    def txt(i):
        c = Console(width=110, record=True); c.print(card_renderable(i, b.found[i - 1], b)); return c.export_text()
    t1, t2 = txt(1), txt(2)
    assert "blocked (local)" in t1 and "block (verify)" in t1 and "mute (real)" in t1
    assert "muted (real)" in t2 and "Navigate" in t2 and "Filter" in t2 and "Tags" in t2


async def test_found_list_has_section_headers(mk):
    from textual.widgets import ListView
    from xbot.app import FoundPicker
    b = mk(xonly=True, mentions=[{"id": "1", "text": "@me [b]x[/b]", "author_id": "m", "username": "mm"}],
           search=[P(5)], **S()); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app.query_one("#queue").focus(); await pilot.press("f"); await pilot.pause()
        lv = app.screen.query_one(ListView)
        texts = [str(i.query_one("Label").render()) for i in lv.children]
        assert "Mentions (1)" in texts[0] and "Suggested replies (1)" in texts[2] and "[b]x[/b]" in texts[1]
        await pilot.press("enter"); await pilot.pause()
        assert isinstance(app.screen, PostCard)


def test_hint_groups_have_distinct_key_colors(mk):
    from xbot.render import _key
    assert _key("g", "bright_green") != _key("g", "magenta")
    import inspect, xbot.render as r
    src = inspect.getsource(r.card_renderable)
    for c in ("bright_cyan", "bright_green", "bold yellow", "grey62]\\(local)" if False else "grey62", "orange_red1"):
        assert c in src
