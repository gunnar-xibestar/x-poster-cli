from xbot.app import XBotApp, PostCard
from tests.test_search import P, S


def tall_post(i=5):
    p = P(i, text="\n".join(f"line {k} of a very tall post body" for k in range(60)))
    p.update(name="Ada L", created_at="2026-10-24T15:30:00.000Z")
    return p


async def test_tall_card_fits_screen_and_scrolls(mk):
    b = mk(xonly=True, search=[tall_post(5), P(6)], **S()); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(120, 30)) as pilot:
        app.action_show_post(1); await pilot.pause(); await pilot.pause()
        scr = app.screen
        assert isinstance(scr, PostCard)
        sc, box = scr.query_one("#card-scroll"), scr.query_one("#card-box")
        assert box.region.bottom <= 30 and box.region.y >= 0  # card never overflows the screen
        assert sc.max_scroll_y > 0  # tall content is scrollable, not clipped
        hints = scr.query_one("#card-hints")
        assert hints.region.height > 0 and hints.region.bottom <= 30  # key help footer stays visible
        await pilot.press("pagedown"); await pilot.pause()
        assert sc.scroll_y > 0
        await pilot.press("pageup"); await pilot.pause()
        assert sc.scroll_y == 0
        await pilot.press("end"); await pilot.pause()
        assert sc.scroll_y == sc.max_scroll_y
        await pilot.press("home"); await pilot.pause()
        assert sc.scroll_y == 0
        await pilot.scroll_down("#card-scroll") if hasattr(pilot, "scroll_down") else None
        await pilot.press("j"); await pilot.pause()
        assert scr.n == 2  # j/k still navigate posts
