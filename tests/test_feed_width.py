import pytest
from xbot.app import XBotApp
from tests.test_search import S
from tests.test_media_layout import P


@pytest.mark.parametrize("w", [120, 200])
async def test_feed_lines_reach_right_edge(mk, w):
    b = mk(xonly=True, search=[P(i, "lorem ipsum dolor sit amet " * 12) for i in range(1, 6)], **S())
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(w, 45)) as pilot:
        b.tick(); await pilot.pause(); await pilot.pause()
        feed = app.query_one("#feed")
        cw = feed.scrollable_content_region.width
        widths = [len(l.text.rstrip()) for l in feed.lines]
        assert widths and max(widths) >= cw - 8, (max(widths), cw)
        # resize: re-wrapped to the new width
        await pilot.resize_terminal(w - 30, 45); await pilot.pause(); await pilot.pause()
        cw2 = feed.scrollable_content_region.width
        assert max(len(l.text.rstrip()) for l in feed.lines) <= cw2 and max(len(l.text.rstrip()) for l in feed.lines) >= cw2 - 8
        b.stopped = True
