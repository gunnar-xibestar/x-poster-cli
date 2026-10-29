from textual.widgets import ListView
import xbot.sample as S


async def test_clicks_only_highlight_and_o_opens(tmp_path):
    app = S.demo_app(tmp_path / "demo")
    async with app.run_test(size=(160, 45)) as pilot:
        await pilot.pause(); await pilot.pause()
        opened = []
        app.action_show_post = lambda n: opened.append(n)
        q = app.query_one("#queue", ListView)
        rows = [c for c in q.children if c.name and app.post_number_for_draft(int(c.name))]
        assert len(rows) >= 2
        app.query_one("#cmd").focus(); await pilot.pause()
        await pilot.click(rows[1]); await pilot.pause()  # unfocused: focus + highlight
        assert not opened and q.has_focus and q.highlighted_child is rows[1]
        await pilot.click(rows[1]); await pilot.pause()  # focused, highlighted: still no open
        await pilot.click(rows[0]); await pilot.pause()  # focused, other item: highlight only
        assert not opened and q.highlighted_child is rows[0]
        await pilot.press("o"); await pilot.pause()
        assert opened == [app.post_number_for_draft(int(rows[0].name))]
        app.query_one("#cmd").focus(); await pilot.pause()
        await pilot.press("o"); await pilot.pause()  # typing in the command line: o types
        assert len(opened) == 1 and app.query_one("#cmd").value.endswith("o")
        app.bot.stopped = True


async def test_click_and_o_in_open_editor_keep_editing(tmp_path):
    app = S.demo_app(tmp_path / "demo")
    async with app.run_test(size=(160, 45)) as pilot:
        await pilot.pause(); await pilot.pause()
        opened = []
        app.action_show_post = lambda n: opened.append(n)
        q = app.query_one("#queue", ListView)
        q.focus(); q.index = 1; await pilot.pause()
        await pilot.press("e"); await pilot.pause()
        ed = app.query_one("#qedit")
        await pilot.click(ed); await pilot.pause()
        assert not opened and app.focused is ed and len(app.query("#qedit")) == 1
        before = ed.value
        await pilot.press("o"); await pilot.pause()
        assert not opened and ed.value != before and "o" in ed.value
        app.bot.stopped = True
