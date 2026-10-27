from textual.widgets import Input, ListView
from xbot.app import XBotApp, CmdInput


async def _type(pilot, s):
    await pilot.press(*s)


async def test_history_up_down_and_persist(mk, tmp_path):
    b = mk()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        inp = app.query_one("#cmd", CmdInput); inp.focus()
        for line in ("/status", "/status", "/help", "/post xai-abc123"):
            inp.value = line; await pilot.press("enter"); await pilot.pause()
        assert inp.history == ["/status", "/help"]  # no dup, no secrets
        await _type(pilot, "/fo")
        await pilot.press("up"); assert inp.value == "/help"
        await pilot.press("up"); assert inp.value == "/status"
        await pilot.press("up"); assert inp.value == "/status"
        await pilot.press("down"); assert inp.value == "/help"
        await pilot.press("down"); assert inp.value == "/fo"  # draft restored
    hist = (tmp_path / "history.txt").read_text().split()
    assert hist == ["/status", "/help"]
    app2 = XBotApp(bot=mk(), autostart=False)
    async with app2.run_test(size=(140, 50)) as pilot:
        assert app2.query_one("#cmd", CmdInput).history == ["/status", "/help"]


async def test_tab_completion(mk):
    b = mk()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        inp = app.query_one("#cmd", CmdInput); inp.focus()
        await _type(pilot, "/fil"); await pilot.press("tab"); assert inp.value == "/filter "
        assert inp.has_focus
        await _type(pilot, "h"); await pilot.press("tab"); assert inp.value == "/filter hide "
        inp.value = "/filter edit spa"; await pilot.press("tab"); assert inp.value == "/filter edit spam "
        inp.value = "/sea"; await pilot.press("tab"); await pilot.pause()
        assert inp.value == "/search" and "tab: search  searchoff  searchon" in (b.log.dir / "actions.jsonl").read_text()


def test_completions_unit():
    c = CmdInput()
    assert c.completions("/filter edit crypto")[0] == "/filter edit crypto-shill "
    assert c.completions("/filter o")[1] == ["on", "off"]
    assert c.completions("hello")[0] == "hello"


async def test_f6_switches_focus(mk):
    app = XBotApp(bot=mk(), autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        inp = app.query_one("#cmd", Input); inp.focus(); await pilot.pause()
        await pilot.press("f6"); await pilot.pause(); assert app.focused is app.query_one("#queue", ListView)
        await pilot.press("f6"); await pilot.pause(); assert app.focused is inp
