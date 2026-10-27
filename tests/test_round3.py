import pytest, requests
from textual.widgets import TextArea, Input
from xbot.xapi import RealX, XNetError
from xbot.app import XBotApp, ReplyEditor, PostCard
from xbot.llm import FakeLLM
from tests.test_search import P, S


class Resp:
    status_code = 200; text = "{}"
    def json(self): return {"data": []}


def _realx(effects):
    x = RealX.__new__(RealX); x._uid = "1"
    calls = []
    class Sess:
        def request(self, m, url, **k):
            calls.append(m); e = effects.pop(0)
            if isinstance(e, Exception): raise e
            return e
    x.s = Sess()
    return x, calls


def test_get_retries_once_then_succeeds():
    x, calls = _realx([requests.ConnectionError("('Connection aborted.', ConnectionResetError(104))"), Resp()])
    assert x._req("GET", "/users/1/mentions", sleep=lambda s: None) == {"data": []} and calls == ["GET", "GET"]


@pytest.mark.parametrize("exc", [requests.ConnectionError("reset"), requests.Timeout("t"),
                                 requests.exceptions.ChunkedEncodingError("c"), requests.RequestException("r")])
def test_get_twice_fails_raises_one_line_xneterror(exc):
    x, calls = _realx([exc, exc])
    with pytest.raises(XNetError) as ei:
        x._req("GET", "/users/1/mentions", sleep=lambda s: None)
    assert "try F5 again" in str(ei.value) and "\n" not in str(ei.value) and len(calls) == 2


def test_post_not_retried():
    x, calls = _realx([requests.ConnectionError("reset"), Resp()])
    with pytest.raises(XNetError):
        x._req("POST", "/tweets", json={}, sleep=lambda s: None)
    assert calls == ["POST"]


def test_tick_survives_network_error(mk):
    b = mk(xonly=True, search=[P(1)], **S())
    def boom(*a, **k): raise XNetError("X connection reset on GET /users/1/mentions, try F5 again")
    b.rx.mentions = boom; b.rx.search_recent = boom
    b.tick(True)
    assert any("try F5 again" in l for l in b.feed)


async def test_f5_never_crashes_on_unexpected_error(mk):
    b = mk(xonly=True, search=[P(1)], **S())
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(120, 40)) as pilot:
        def boom(*a, **k): raise requests.ConnectionError("reset")
        b.tick = boom
        app.query_one("#queue").focus()
        await pilot.press("f5"); await pilot.pause()
        con = "\n".join(str(l.text) for l in app.query_one("#console").lines)
        assert app.is_running and "try again" in con


async def test_r_from_search_card_opens_blank_editor(mk):
    b = mk(FakeLLM(["grok text"]), search=[P(1, text="linux")], **S()); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#queue").focus(); await pilot.press("f"); await pilot.pause()
        await pilot.press("enter"); await pilot.pause()
        assert isinstance(app.screen, PostCard)
        await pilot.press("r"); await pilot.pause(); await pilot.pause()
        ed = app.screen
        assert isinstance(ed, ReplyEditor) and ed.query_one(TextArea).has_focus and ed.text == ""
        await pilot.press(*"mine"); await pilot.pause()
        assert ed.text == "mine"


async def test_queue_click_only_highlights_o_opens(mk):
    b = mk(FakeLLM(["hey"]), [{"id": "7", "text": "@me sup"}], post_every_n_ticks=0)
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 40)) as pilot:
        b.tick(); app.refresh_ui(); await pilot.pause()
        app.query_one("#cmd").focus(); await pilot.pause()
        q = app.query_one("#queue")
        item = [c for c in q.children if c.name][0]
        await pilot.click(item); await pilot.pause()
        await pilot.click(item); await pilot.pause()
        assert q.has_focus and q.highlighted_child is item and not isinstance(app.screen, PostCard)
        await pilot.press("o"); await pilot.pause()
        assert isinstance(app.screen, PostCard)


def test_long_post_with_video_detected():
    """Shaped like status 2114062457178054840 (@geraldposner): note_tweet long text, native video via includes."""
    from xbot.xapi import attach_media
    long = "word " * 80
    resp = {"data": [{"id": "2114062457178054840", "text": long[:270] + "… https://t.co/abc",
                      "attachments": {"media_keys": ["13_999"]},
                      "note_tweet": {"text": long + " https://t.co/vid", "entities": {"urls": [
                          {"url": "https://t.co/vid", "expanded_url": "https://x.com/geraldposner/status/2114062457178054840/video/1",
                           "display_url": "pic.x.com/vid"}]}}}],
            "includes": {"media": [{"media_key": "13_999", "type": "video", "preview_image_url": "https://pbs.twimg.com/p.jpg",
                                    "variants": [{"content_type": "video/mp4", "bit_rate": 832000, "url": "https://video.twimg.com/v.mp4"}]}]}}
    p = attach_media(resp)[0]
    assert [{k: v for k, v in m.items() if k != "variants"} for m in p["media"]] == [{"type": "video", "url": "https://video.twimg.com/v.mp4", "preview_image_url": "https://pbs.twimg.com/p.jpg"}] and p["media"][0]["variants"] and p["text"].startswith("word word")
    # media only via the note_tweet link (no includes): still media
    resp["data"][0].pop("attachments", None); resp["data"][0]["text"] = long[:270]; resp["includes"] = {}
    resp["data"][0]["note_tweet"]["entities"]["urls"][0]["display_url"] = "x.com/..."
    p = attach_media(resp)[0]
    assert p["media"] and p["media"][0]["type"] == "video"


def test_search_and_mentions_request_media_fields():
    from xbot.xapi import MEDIA_PARAMS
    import inspect, xbot.xapi as xa
    assert "attachments.media_keys" in MEDIA_PARAMS["expansions"]
    assert {"type", "url", "preview_image_url"} <= set(MEDIA_PARAMS["media.fields"].split(","))
    assert inspect.getsource(xa.RealX.search_recent).count("note_tweet") and inspect.getsource(xa.RealX.mentions).count("note_tweet")


@pytest.mark.parametrize("env,want", [
    ({"WT_SESSION": "x", "TERM": "xterm-256color"}, "sixel"),
    ({"KITTY_WINDOW_ID": "1", "TERM": "xterm-kitty"}, "tgp"),
    ({"TERM": "xterm-ghostty", "TERM_PROGRAM": "ghostty"}, "tgp"),
    ({"WEZTERM_PANE": "0", "TERM": "xterm-256color"}, "sixel"),
    ({"KONSOLE_VERSION": "230800", "TERM": "xterm-256color"}, "sixel"),
    ({"TERM": "foot"}, "sixel"),
    ({"TERM": "xterm", "XTERM_VERSION": "XTerm(390)"}, "sixel"),
    ({"TERM": "xterm-256color"}, "halfblock"),  # GNOME Terminal etc.
    ({"WT_SESSION": "x", "TMUX": "/tmp/t"}, "halfblock"),
])
def test_pick_renderer_env(env, want):
    from xbot.app import pick_renderer
    assert pick_renderer("auto", env) == want


def test_pick_renderer_override_and_sizes():
    from xbot.app import pick_renderer, large_media_url
    assert pick_renderer("halfblock", {"WT_SESSION": "x"}) == "halfblock" and pick_renderer("off", {}) == "off"
    assert pick_renderer("sixel", {}) == "sixel"
    assert large_media_url("https://pbs.twimg.com/media/AbC.jpg") == "https://pbs.twimg.com/media/AbC?format=jpg&name=large"
    assert large_media_url("https://pbs.twimg.com/media/AbC?format=png&name=small").endswith("format=png&name=large")
    assert large_media_url("https://video.twimg.com/v.mp4") == "https://video.twimg.com/v.mp4"


