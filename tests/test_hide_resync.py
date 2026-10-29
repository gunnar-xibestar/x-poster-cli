from xbot.app import pick_after_hide


def test_pick_prefers_last_viewed_then_next_then_prev():
    old = [1, 2, 3, 4, 5]
    assert pick_after_hide(old, [1, 2, 4, 5], 3, prefer=4) == 4
    assert pick_after_hide(old, [1, 2, 4, 5], 3, prefer=3) == 4  # hidden prefer -> next after cur
    assert pick_after_hide(old, [1, 2, 4, 5], 3) == 4
    assert pick_after_hide(old, [1, 2, 3, 4], 5) == 4           # last one hidden -> previous
    assert pick_after_hide(old, [2], 4) == 2
    assert pick_after_hide(old, [], 3) is None
    assert pick_after_hide(old, [1, 2, 3], 2) == 2              # still visible: stay


from xbot.app import XBotApp, PostCard, FoundPicker
from tests.test_search import P, S


def _viewer_hides(app, hide):
    """Fake media viewer: hides posts `hide` (like r / t) and reports the last item shown."""
    def fake(*a, **k):
        for n in hide:
            app.bot.hide_post(n, forever=True)
        k["state"]["last"] = {"n": k["start_n"]}
        return "mpv"
    return fake


async def test_viewer_hide_rebuilds_found_list_and_moves_card(mk, monkeypatch):
    from xbot import video
    b = mk(xonly=True, search=[P(5), P(6), P(7)], **S()); b.tick()
    for p in b.found:
        p["media"] = [{"type": "photo", "url": "https://pbs.twimg.com/a.jpg"}]
    monkeypatch.setattr(b, "media_items", lambda n: b.found_post(n)["media"], raising=False)
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 40)) as pilot:
        app.query_one("#queue").focus()
        await pilot.press("f"); await pilot.pause()
        app.action_show_post(2); await pilot.pause()
        card = app.screen
        assert isinstance(card, PostCard) and card.n == 2
        monkeypatch.setattr(video, "run_mpv", _viewer_hides(app, [2]))
        monkeypatch.setattr(app, "suspend", lambda: __import__("contextlib").nullcontext())
        app.play_media(2, which=lambda c: "/usr/bin/mpv"); await pilot.pause()
        assert app.screen is card and card.n == 3  # next visible after the hidden one
        picker = next(s for s in app.screen_stack if isinstance(s, FoundPicker))
        assert [n for n, _ in picker.found] == [1, 3]
        monkeypatch.setattr(video, "run_mpv", _viewer_hides(app, [3]))
        app.play_media(3, which=lambda c: "/usr/bin/mpv"); await pilot.pause()
        assert card.n == 1  # last one hidden -> previous
        monkeypatch.setattr(video, "run_mpv", _viewer_hides(app, [1]))
        app.play_media(1, which=lambda c: "/usr/bin/mpv"); await pilot.pause(); await pilot.pause()
        assert not isinstance(app.screen, (PostCard, FoundPicker))  # nothing left: both closed


async def test_h_in_card_rebuilds_found_list(mk):
    b = mk(xonly=True, search=[P(5), P(6), P(7)], **S()); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 40)) as pilot:
        app.query_one("#queue").focus()
        await pilot.press("f"); await pilot.pause()
        app.action_show_post(3); await pilot.pause()
        await pilot.press("h"); await pilot.pause(); await pilot.pause()
        assert isinstance(app.screen, PostCard) and app.screen.n == 2
        picker = next(s for s in app.screen_stack if isinstance(s, FoundPicker))
        assert [n for n, _ in picker.found] == [1, 2]


async def test_a_d_navigate_the_search_card(mk):
    b = mk(xonly=True, search=[P(5), P(6), P(7)], **S()); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 40)) as pilot:
        app.query_one("#queue").focus()
        await pilot.press("f"); await pilot.pause()
        app.action_show_post(2); await pilot.pause()
        await pilot.press("d"); await pilot.pause(); assert app.screen.n == 3
        await pilot.press("a"); await pilot.pause(); assert app.screen.n == 2
        await pilot.press("left"); await pilot.pause(); assert app.screen.n == 1
