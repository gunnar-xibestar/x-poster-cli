from xbot.app import XBotApp, ReplyEditor, PostCard
from tests.test_search import P, S


def _stub(monkeypatch, opened):
    import xbot.opener
    monkeypatch.setattr(xbot.opener, "open_url_async", lambda url, done: opened.append(url))


def test_bot_browser_reply_records_sent(mk):
    b = mk(xonly=True, search=[P(5), P(6)], **S()); b.tick()
    p0 = b.found[0]; other = b.found[1]["id"]
    d = b.browser_reply_to_found(1, "nice one")
    assert d.status == "sent" and d.text == "nice one" and str(d.in_reply_to) == p0["id"]
    assert b.queue.get(d.id) in b.queue.items and d not in b.queue.pending()
    assert (p0.get("conversation_id") or p0["id"]) in b.state.replied_threads
    # replied post removed from found (and found.json), the rest renumbered, F5 cursor pruned
    assert [p["id"] for p in b.found] == [other]
    import json
    assert [x["id"] for x in json.loads(b.found_path.read_text())["posts"]] == [other]
    assert str(p0["id"]) not in map(str, b.state.feed_shown)
    assert [b.found_post(n)["id"] for n in b.nav_order()] == [other]


async def _open_editor(app, pilot, n):
    app.action_show_post(n); await pilot.pause()
    await pilot.press("r"); await pilot.pause()
    assert isinstance(app.screen, ReplyEditor)


async def test_ctrl_b_saves_closes_and_opens_next(mk, monkeypatch):
    opened = []; _stub(monkeypatch, opened)
    b = mk(xonly=True, search=[P(5), P(6)], **S()); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 40)) as pilot:
        order = list(b.nav_order()); ids = [b.found_post(n)["id"] for n in order]
        await _open_editor(app, pilot, order[0])
        await pilot.press(*"hello"); await pilot.press("ctrl+b"); await pilot.pause(); await pilot.pause()
        assert opened and "in_reply_to=" in opened[0] and "text=hello" in opened[0]
        assert isinstance(app.screen, PostCard) and app.screen.post["id"] == ids[1]
        assert len(app.screen_stack) == 2  # old card closed, only the new one on top of base
        assert any(d.status == "sent" and d.text == "hello" for d in b.queue.items)
        # last post: Ctrl+B returns to the list
        await pilot.press("r"); await pilot.pause()
        await pilot.press(*"bye"); await pilot.press("ctrl+b"); await pilot.pause(); await pilot.pause()
        assert not isinstance(app.screen, (PostCard, ReplyEditor))


async def test_ctrl_e_still_queues_and_keeps_card(mk):
    b = mk(xonly=True, search=[P(5), P(6)], **S()); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 40)) as pilot:
        n = b.nav_order()[0]
        await _open_editor(app, pilot, n)
        await pilot.press(*"q1"); await pilot.press("ctrl+e"); await pilot.pause()
        assert isinstance(app.screen, PostCard) and app.screen.n == n
        assert any(d.status == "pending" and d.text == "q1" for d in b.queue.items)


async def test_ctrl_b_empty_only_opens_post(mk, monkeypatch):
    b = mk(xonly=True, search=[P(5)], **S()); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 40)) as pilot:
        b.opener = lambda url, done: done("wslview")
        await _open_editor(app, pilot, 1)
        await pilot.press("ctrl+b"); await pilot.pause()
        assert isinstance(app.screen, ReplyEditor) and not any(d.status == "sent" for d in b.queue.items)


async def test_ctrl_b_from_found_list_removes_post(mk, monkeypatch):
    """Regression: the replied post stayed (top, highlighted) in the open Found posts list."""
    from xbot.app import FoundPicker
    opened = []; _stub(monkeypatch, opened)
    b = mk(xonly=True, search=[P(5), P(6), P(7)], **S()); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 40)) as pilot:
        ids = [b.found_post(n)["id"] for n in b.nav_order()]
        app.push_screen(FoundPicker(b.feed_found())); await pilot.pause()
        await _open_editor(app, pilot, b.nav_order()[0])
        await pilot.press(*"hi"); await pilot.press("ctrl+b")
        for _ in range(4):
            await pilot.pause()
        assert isinstance(app.screen, PostCard) and app.screen.post["id"] == ids[1]
        assert ids[0] not in [p["id"] for p in b.found]
        pick = next(s for s in app.screen_stack if isinstance(s, FoundPicker))
        assert [p["id"] for _, p in pick.found] == ids[1:]
        await pilot.press("escape"); await pilot.pause()
        names = [i.name for i in app.screen.query("ListItem") if i.name]
        assert names == [str(n) for n in b.nav_order()] and len(names) == 2


def test_purge_replied(mk):
    b = mk(xonly=True, search=[P(5), P(6), P(7)], **S()); b.tick()
    b.found[0]["replied"] = True; b.found[2]["replied"] = True
    b.state.feed_shown = [p["id"] for p in b.found]
    assert b.purge_replied() == 2 and [p["id"] for p in b.found] == ["6"]
    assert list(map(str, b.state.feed_shown)) == ["6"] and b.nav_order() == [1]
    import json
    assert [(p["n"], p["id"]) for p in json.loads(b.found_path.read_text())["posts"]] == [(1, "6")]
    assert b.purge_replied() == 0
