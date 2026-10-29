from textual.widgets import ListView
import xbot.sample as S
from xbot.app import QEdit

LONG = "word " * 60 + "THE-END-OF-REPLY"


def _vis(item, cls):
    return item.query_one(f".{cls}").display


async def _setup(tmp_path, pilot, app):
    await pilot.pause(); await pilot.pause()
    q = app.query_one("#queue", ListView)
    items = [c for c in q.children if c.name]
    did = int(items[0].name)
    app.bot.queue.edit(did, LONG); app.refresh_ui(); await pilot.pause(); await pilot.pause()
    q.focus(); q.index = q.children.index([c for c in q.children if c.name == str(did)][0]); await pilot.pause()
    return q, did


async def test_selected_card_expands_full_text_others_compact(tmp_path):
    app = S.demo_app(tmp_path / "demo")
    async with app.run_test(size=(160, 45)) as pilot:
        q, did = await _setup(tmp_path, pilot, app)
        sel = q.highlighted_child
        assert sel.name == str(did)
        assert _vis(sel, "qfull") and _vis(sel, "qreply") and not _vis(sel, "qcompact")
        assert "THE-END-OF-REPLY" in str(sel.query_one(".qreply").render())
        assert "THE-END-OF-REPLY" not in str(sel.query_one(".qcompact").render())  # compact clips
        others = [c for c in q.children if c.name and c is not sel]
        assert others and all(_vis(o, "qcompact") and not _vis(o, "qfull") for o in others)
        d = app.bot.queue.get(did)
        if d.context:
            assert d.context[-20:] in str(sel.query_one(".qfull").render())
        app.bot.stopped = True


async def test_e_edits_in_place_save_and_cancel(tmp_path):
    app = S.demo_app(tmp_path / "demo")
    async with app.run_test(size=(160, 45)) as pilot:
        q, did = await _setup(tmp_path, pilot, app)
        item = q.highlighted_child
        await pilot.press("e"); await pilot.pause()
        ed = app.query_one("#qedit", QEdit)
        assert ed.parent is item and ed.has_focus and ed.text == LONG and not _vis(item, "qreply")
        await pilot.press("e"); await pilot.press("e"); await pilot.pause()  # typed, still one editor
        assert len(app.query("#qedit")) == 1
        await pilot.press("escape"); await pilot.pause(); await pilot.pause()
        assert not app.query("#qedit") and app.bot.queue.get(did).text == LONG
        await pilot.press("e"); await pilot.pause()
        app.query_one("#qedit", QEdit).value = "new reply text"
        await pilot.press("ctrl+s"); await pilot.pause(); await pilot.pause()
        assert not app.query("#qedit") and app.bot.queue.get(did).text == "new reply text"
        await pilot.pause()
        sel = q.highlighted_child
        assert sel.name == str(did) and _vis(sel, "qreply") and "new reply text" in str(sel.query_one(".qreply").render())
        await pilot.press("e"); await pilot.pause()
        app.query_one("#qedit").value = "via enter"
        await pilot.press("enter"); await pilot.pause(); await pilot.pause()
        assert app.bot.queue.get(did).text == "via enter"
        app.bot.stopped = True
