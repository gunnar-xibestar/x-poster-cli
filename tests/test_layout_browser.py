from textual.widgets import TextArea, RichLog, Input
from xbot.app import XBotApp, ReplyEditor, PostCard, FoundPicker
from tests.test_search import P, S


def _text(log):
    return "\n".join(str(l.text) for l in log.lines)


def _app(mk):
    b = mk(xonly=True, search=[P(8, text="linux rocks")], **S())
    urls = []
    b.opener = lambda url, done: (urls.append(url), done("test"))
    return b, XBotApp(bot=b, autostart=False), urls


async def test_posts_in_feed_output_in_console(mk):
    b, app, _ = _app(mk)
    async with app.run_test(size=(140, 50)) as pilot:
        b.tick(); await pilot.pause()
        b.log.event("error", "boom-err"); await pilot.pause()
        feed, con = _text(app.query_one("#feed", RichLog)), _text(app.query_one("#console", RichLog))
        assert "linux rocks" in feed and "boom-err" not in feed
        assert "boom-err" in con and "linux rocks" not in con


async def test_f3_hides_console_and_slash_restores(mk):
    b, app, _ = _app(mk)
    async with app.run_test(size=(140, 50)) as pilot:
        h0 = app.query_one("#feed").size.height
        app.query_one("#queue").focus()
        await pilot.press("f3"); await pilot.pause()
        assert not app.console_visible and app.query_one("#feed").size.height > h0
        assert any(b.key == "f3" and b.show for b in app.BINDINGS if hasattr(b, "key"))
        await pilot.press("slash"); await pilot.pause()
        inp = app.query_one("#cmd", Input)
        assert app.console_visible and inp.has_focus and inp.value == "/"
        await pilot.press("f3"); await pilot.pause()
        assert not app.console_visible
        await pilot.press("f3"); await pilot.pause()
        assert app.console_visible


async def test_found_picker_centered(mk):
    b, app, _ = _app(mk)
    async with app.run_test(size=(140, 50)) as pilot:
        b.tick(); app.query_one("#queue").focus(); await pilot.press("f"); await pilot.pause()
        assert isinstance(app.screen, FoundPicker)
        r = app.screen.query_one("#picker").region
        assert abs(r.x - (140 - r.right)) <= 1 and abs(r.y - (50 - r.bottom)) <= 1


async def test_g_queue_then_o_opens_prefilled(mk):
    b, app, urls = _app(mk)
    async with app.run_test(size=(140, 50)) as pilot:
        b.tick(); app.action_show_post(1); await pilot.pause()
        await pilot.press("g"); await pilot.pause()
        ed = app.screen; ed.query_one(TextArea).text = "hello there"; await pilot.pause()
        await pilot.press("ctrl+e"); await pilot.pause()
        assert isinstance(app.screen, PostCard)
        await pilot.press("o"); await pilot.pause()
        assert urls and "intent/post" in urls[-1] and "hello%20there" in urls[-1]


async def test_ctrl_b_in_editor_opens_prefilled(mk, monkeypatch):
    import xbot.opener as op
    b, app, urls = _app(mk)
    monkeypatch.setattr(op, "open_url_async", lambda url, done: (urls.append(url), done("t")))
    async with app.run_test(size=(140, 50)) as pilot:
        b.tick(); app.action_show_post(1); await pilot.pause()
        await pilot.press("g"); await pilot.pause()
        app.screen.query_one(TextArea).text = "yo"; await pilot.pause()
        await pilot.press("ctrl+b"); await pilot.pause()
        assert urls and "text=yo" in urls[-1]


async def test_a_in_queue_opens_browser_for_search_reply(mk):
    b, app, urls = _app(mk)
    async with app.run_test(size=(140, 50)) as pilot:
        b.tick(); b.queue_reply_to_found(1, "nice one"); app.refresh_ui(); await pilot.pause()
        app.query_one("#queue").focus(); await pilot.pause()
        await pilot.press("a"); await pilot.pause()
        assert urls and "nice%20one" in urls[-1] and b.dry_x.sent == []


async def test_a_after_inplace_edit_uses_edited_text(mk):
    b, app, urls = _app(mk)
    async with app.run_test(size=(140, 50)) as pilot:
        b.tick(); b.queue_reply_to_found(1, "orig"); app.refresh_ui(); await pilot.pause()
        app.query_one("#queue").focus(); await pilot.pause()
        await pilot.press("e"); await pilot.pause()
        q = app.query_one("#qedit", Input); q.value = "edited text"
        await pilot.press("enter"); await pilot.pause()
        app.query_one("#queue").focus(); await pilot.pause()
        await pilot.press("a"); await pilot.pause()
        assert urls and "edited%20text" in urls[-1] and "orig" not in urls[-1]


async def test_g_edit_after_grok_then_o_uses_user_text(mk):
    b, app, urls = _app(mk)
    async with app.run_test(size=(140, 50)) as pilot:
        b.tick(); app.action_show_post(1); await pilot.pause()
        await pilot.press("g"); await pilot.pause()
        ta = app.screen.query_one(TextArea); ta.text = "first"; await pilot.pause()
        ta.text = "user edited"; await pilot.pause()
        await pilot.press("ctrl+e"); await pilot.pause()
        await pilot.press("o"); await pilot.pause()
        assert "user%20edited" in urls[-1] and "first" not in urls[-1]


async def test_popups_show_esc_hint_top_left(mk):
    b, app, _ = _app(mk)
    async with app.run_test(size=(140, 50)) as pilot:
        b.tick(); app.query_one("#queue").focus()
        await pilot.press("f"); await pilot.pause()
        assert "esc" in str(app.screen.children[0].border_title)
        app.action_show_post(1); await pilot.pause()
        await pilot.press("g"); await pilot.pause()
        assert "esc" in str(app.screen.children[0].border_title)


async def test_post_card_centered_with_esc_hint_inside(mk):
    b, app, _ = _app(mk)
    async with app.run_test(size=(120, 40)) as pilot:
        b.tick(); app.query_one("#queue").focus(); await pilot.press("f"); await pilot.pause()
        await pilot.press("enter"); await pilot.pause()
        assert isinstance(app.screen, PostCard)
        w = app.screen.children[0]; r = w.region
        assert abs(r.x - (120 - r.right)) <= 1 and abs(r.y - (40 - r.bottom)) <= 1 and r.x > 5
        from rich.console import Console
        from xbot.render import card_renderable; c = Console(width=100, record=True); c.print(card_renderable(1, b.found[0], b)); assert "esc to back" in c.export_text().lower()
