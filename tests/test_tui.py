import pytest
from xbot.app import XBotApp
from xbot.llm import FakeLLM


@pytest.mark.asyncio
async def test_tui_launch_and_approve(mk):
    b = mk(FakeLLM(["hey"]), [{"id": "7", "text": "@me sup"}], post_every_n_ticks=0)
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test() as pilot:
        b.tick(); app.refresh_ui(); await pilot.pause()
        app.query_one("#queue").focus(); await pilot.pause()
        await pilot.press("a"); await pilot.pause()
        assert b.dry_x.sent and b.dry_x.sent[0]["in_reply_to"] == "7"
        app.query_one("#cmd").focus()
        await pilot.press(*"/post typed"); await pilot.press("enter"); await pilot.pause()
        assert b.queue.pending()[-1].text == "typed" and len(b.dry_x.sent) == 1
        await pilot.press(*"/stop"); await pilot.press("enter"); await pilot.pause()
    assert b.stopped


@pytest.mark.parametrize("key", ["ctrl+c", "ctrl+q"])
async def test_ctrl_c_quits_and_persists(mk, key):
    from xbot.queue import DraftQueue
    b = mk()
    b.handle(__import__("xbot.commands").commands.parse("/post keep me"))
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test() as pilot:
        app.query_one("#cmd").focus()
        await pilot.press(key); await pilot.pause()
    assert b.stopped
    assert DraftQueue(b.queue.path).pending()[0].text == "keep me"
    assert (b.state.path).exists()
    assert "stopped" in b.log.path.read_text().splitlines()[-1]
