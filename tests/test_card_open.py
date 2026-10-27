import subprocess
from textual.widgets import Input, Static
from xbot.commands import parse
from xbot.opener import open_url
from xbot.render import card_plain, card_renderable, feed_text, fmt_time
from xbot.app import XBotApp, PostCard, FoundPicker
from tests.test_search import P, S

URL = "https://x.com/i/status/5"


def rich_post(i=5):
    p = P(i, text="Kernel [b]6.20[/b] released")
    p.update(name="Ada L", created_at="2026-10-24T15:30:00.000Z",
             public_metrics={"like_count": 42, "retweet_count": 7, "reply_count": 3, "quote_count": 1})
    return p


def test_opener_order_and_fallbacks():
    calls = []
    have = {"explorer.exe", "powershell.exe", "xdg-open"}
    m = open_url(URL, which=lambda c: c in have, popen=lambda cmd, **k: calls.append(cmd), wb=lambda u: False, wsl=True)
    assert m == "powershell.exe" and calls[0][0] == "powershell.exe"  # never explorer.exe
    have.add("wslview"); calls.clear()
    assert open_url(URL, which=lambda c: c in have, popen=lambda cmd, **k: calls.append(cmd), wsl=True) == "wslview"
    def boom(cmd, **k): raise OSError
    assert open_url(URL, which=lambda c: True, popen=boom, wb=lambda u: True) == "webbrowser"
    assert open_url(URL, which=lambda c: False, popen=boom, wb=lambda u: False) is None
    assert open_url("javascript:x", which=lambda c: True, popen=boom) is None


def test_card_contents_la_time_and_escape():
    p = dict(rich_post(), source="search")
    assert fmt_time("2026-10-24T15:30:00.000Z") == "Sat Oct 24 2026, 8:30 AM PDT"
    t = card_plain(1, p)
    assert "Ada L @ua1" in t and "likes 42" in t and "reposts 7" in t and "quotes 1" in t and URL in t
    from rich.console import Console
    c = Console(width=100, record=True); c.print(card_renderable(1, p))
    out = c.export_text()
    assert "[b]6.20[/b]" in out and "8:30 AM PDT" in out and "♥ 42" in out


def test_show_and_open_commands(mk):
    b = mk(xonly=True, search=[rich_post()], **S()); b.tick()
    opened = []
    b.opener = lambda url, done: (opened.append(url), done("wslview"))
    b.handle(parse("/open 1")); assert opened == [URL] and "via wslview" in b.feed[-1]
    b.opener = lambda url, done: done(None)
    b.handle(parse("/open #1")); assert "open manually: " + URL in b.feed[-1]
    b.handle(parse("/show 1")); assert "Ada L" in b.feed[-1]


def test_feed_line_is_clickable():
    t = feed_text({"ts": "2026-10-24T08:00:00-0700", "kind": "found", "msg": "", "n": 3, "source": "search",
                   "author": "a", "snippet": "s", "tweet_id": "9"})
    metas = [s.style.meta for s in t.spans if hasattr(s.style, "meta") and s.style.meta]
    assert any(m.get("@click") == "app.show_post(3)" for m in metas)


async def test_tui_picker_card_keys(mk):
    b = mk(xonly=True, search=[rich_post(5), P(6)], **S()); b.tick()
    opened = []
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 40)) as pilot:
        b.opener = lambda url, done: (opened.append(url), done("wslview"))
        app.query_one("#queue").focus()
        await pilot.press("f"); await pilot.pause()
        assert isinstance(app.screen, FoundPicker)
        await pilot.press("enter"); await pilot.pause()
        assert isinstance(app.screen, PostCard) and app.screen.n == 1
        await pilot.press("o"); await pilot.pause(); assert opened == [URL]
        await pilot.press("escape"); await pilot.pause(); assert not isinstance(app.screen, PostCard)
        app.action_show_post(2); await pilot.pause()
        await pilot.press("r"); await pilot.pause()
        from xbot.app import ReplyEditor
        from textual.widgets import TextArea
        ed = app.screen
        assert isinstance(ed, ReplyEditor) and ed.n == 2 and ed.query_one(TextArea).has_focus
        await pilot.press(*"hey"); await pilot.pause()
        assert ed.query_one(TextArea).text == "hey" and app._base().query_one("#cmd", Input).value == ""
        await pilot.press("escape"); await pilot.pause(); await pilot.press("escape"); await pilot.pause()
        app._run("/show 1"); await pilot.pause(); assert isinstance(app.screen, PostCard)


async def test_mouse_click_on_feed_number_opens_card(mk):
    b = mk(xonly=True, search=[P(5)], **S()); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        feed = app.query_one("#feed")
        y, line = next((y, l.text) for y, l in enumerate(feed.lines) if "#1 " in l.text and "FOUND" in l.text)
        await pilot.click("#feed", offset=(line.index("#1 ") + 2, y + 1)); await pilot.pause()
        assert isinstance(app.screen, PostCard)
