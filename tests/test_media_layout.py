from xbot.app import XBotApp
from tests.test_search import S


def P(i, text):
    return {"id": str(i), "text": text, "author_id": f"s{i}", "username": f"s{i}", "conversation_id": str(i)}


LONG = "\n".join(f"line {k} of a very long post" for k in range(80))


async def test_pagedown_scrolls_post_text(mk):
    b = mk(xonly=True, search=[P(1, LONG)], **S()); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(120, 30)) as pilot:
        app.action_show_post(1); await pilot.pause()
        sc = app.screen.query_one("#card-scroll")
        await pilot.press("pagedown"); await pilot.pause()
        assert sc.scroll_y > 0
        b.stopped = True
