import asyncio
from xbot.commands import parse, CommandError
from xbot.app import XBotApp
from xbot.config import Config
from tests.test_search import P, S
import pytest


def test_no_auto_poll(tmp_path):
    assert not hasattr(Config(), "auto_poll") and not hasattr(Config(), "poll_interval")
    with pytest.raises(CommandError):
        parse("/auto on")
    (tmp_path / "config.json").write_text('{"auto_poll": true, "poll_interval": 5, "model": "m1"}')
    c = Config.load(tmp_path)  # old configs still load
    assert c.model == "m1" and not hasattr(c, "auto_poll")


def test_manual_tick_forces_search(mk):
    b = mk(xonly=True, search=[P(1), P(2)], **S(search_every_n_ticks=5, search_max_results=1))
    b.tick(force_search=True); assert len(b.dry_x.searches) == 1
    b.handle(parse("/tick")); assert len(b.dry_x.searches) == 2 and len(b.found) == 2
    assert "auto=" not in b.status() and "last check=never" not in b.status()
    b.handle(parse("/searchoff")); b.handle(parse("/tick")); assert len(b.dry_x.searches) == 2


async def test_startup_one_check_then_idle(mk):
    b = mk(xonly=True, search=[P(1)], **S(search_every_n_ticks=1))
    app = XBotApp(bot=b, autostart=True)
    async with app.run_test() as pilot:
        await asyncio.sleep(2.5)
        assert b.ticks == 1 and len(b.dry_x.searches) == 1
        await asyncio.sleep(1.5)
        assert b.ticks == 1  # no automatic polling
        await pilot.press("ctrl+c")
