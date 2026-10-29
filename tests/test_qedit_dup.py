from textual.widgets import ListView
from xbot.app import QEdit
import xbot.sample as S


async def _count(app, pilot):
    await pilot.pause(); await pilot.pause()
    return len(app.query("#qedit"))


async def test_edit_never_mounts_two_qedit(tmp_path):
    app = S.demo_app(tmp_path / "demo")
    async with app.run_test(size=(160, 45)) as pilot:
        await pilot.pause(); await pilot.pause()
        q = app.query_one("#queue", ListView)
        assert len(q.children) >= 3
        q.focus(); q.index = 1; await pilot.pause()
        await pilot.press("e"); assert await _count(app, pilot) == 1
        await pilot.press("e")  # typed into the open editor
        assert await _count(app, pilot) == 1
        q.focus(); await pilot.pause()  # editor left open, focus back on the list (mouse click)
        await app.run_action("edit")  # e again on the same draft: reuse
        assert await _count(app, pilot) == 1 and isinstance(app.focused, QEdit)
        q.focus(); q.index = 2; await pilot.pause()
        await app.run_action("edit")  # another draft while one is open: the old one goes first
        assert await _count(app, pilot) == 1
        assert app.query_one("#qedit").parent is q.children[2]
        await pilot.press("escape"); assert await _count(app, pilot) == 0
        q.focus(); q.index = 1; await pilot.pause()
        await pilot.press("e"); assert await _count(app, pilot) == 1  # e after Esc
        await pilot.press("enter"); assert await _count(app, pilot) == 0  # submit removes it
        q.focus(); q.index = len(q.children) - 1; await pilot.pause()
        await pilot.press("e"); assert await _count(app, pilot) == 1  # last (mention/suggested) section
        q.focus(); q.index = 1; await pilot.pause()
        await pilot.press("e"); assert await _count(app, pilot) == 1
        app.bot.stopped = True
