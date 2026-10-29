import os, stat
from xbot import search_history as sh
from xbot.app import XBotApp, SearchHistoryPicker
from xbot.commands import parse
from tests.test_search import P, S


def test_dedupe_newest_first_cap_and_private(tmp_path):
    for q in ["linux", "rust", "LINUX", "  go   lang "]:
        sh.add(tmp_path, q)
    assert sh.load(tmp_path) == ["go lang", "LINUX", "rust"]
    assert stat.S_IMODE(os.stat(tmp_path / sh.NAME).st_mode) == 0o600
    for i in range(sh.CAP + 20):
        sh.add(tmp_path, f"q{i}")
    h = sh.load(tmp_path); assert len(h) == sh.CAP and h[0] == f"q{sh.CAP + 19}"
    (tmp_path / sh.NAME).write_text("garbage"); assert sh.load(tmp_path) == []


def test_search_command_records_in_bot_state_dir(mk):
    b = mk(xonly=True, search=[P(1)], **S())
    b.handle(parse("/search kernel panic"))
    assert sh.load(b.state_dir) == ["kernel panic"]


async def test_h_opens_picker_and_enter_fills_input(mk):
    b = mk(xonly=True, search=[P(1)], **S())
    sh.add(b.state_dir, "old one"); sh.add(b.state_dir, "newest")
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#queue").focus()
        await pilot.press("h"); await pilot.pause()
        assert isinstance(app.screen, SearchHistoryPicker)
        await pilot.press("down", "enter"); await pilot.pause()
        assert not isinstance(app.screen, SearchHistoryPicker)
        assert app.query_one("#cmd").value == "/search old one"
        # typing h in the input must not open the picker
        await pilot.press("h"); await pilot.pause()
        assert not isinstance(app.screen, SearchHistoryPicker)
        await pilot.press("ctrl+c")


async def test_esc_closes_picker(mk):
    b = mk(xonly=True, search=[P(1)], **S())
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#queue").focus()
        await pilot.press("h"); await pilot.pause()
        assert isinstance(app.screen, SearchHistoryPicker)
        await pilot.press("escape"); await pilot.pause()
        assert not isinstance(app.screen, SearchHistoryPicker)
        await pilot.press("ctrl+c")


async def test_console_height_doubled_and_capped(mk):
    b = mk(xonly=True, search=[P(1)], **S())
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(120, 60)) as pilot:
        app.show_console(True); await pilot.pause()
        assert app.query_one("#console-box").size.height + 2 >= 24 or app.query_one("#console-box").outer_size.height == 24
    async with XBotApp(bot=b, autostart=False).run_test(size=(80, 20)) as pilot:
        pilot.app.show_console(True); await pilot.pause()
        assert pilot.app.query_one("#console-box").outer_size.height <= 9
