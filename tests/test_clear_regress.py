from tests.conftest import queue_predrafts
from xbot.app import XBotApp
from xbot.state import BotState
from tests.test_round_drafting import JsonLLM
from tests.test_search import P, S


async def test_x_clears_queue_and_its_prefill_then_refills_paced(mk):
    llm = JsonLLM()
    b = mk(llm, search=[P(i) for i in range(1, 40)], draft_batch=8, prefill_max=8, **S(max_pending=4)); b.tick()
    assert not b.queue.pending() and b.state.prefill  # Grok pre-drafts only; queue is manual
    queue_predrafts(b); assert len(b.queue.pending()) >= 4
    for d in b.queue.pending()[4:]: b.queue.reject(d.id)
    b.tick()
    old = {d.id for d in b.queue.pending()}
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("x"); await pilot.pause()
        await pilot.press("Y"); await pilot.pause(); await pilot.pause()
        assert not b.queue.pending() and not b.state.prefill
        assert "cleared 4 pending suggested drafts" in b.log.path.read_text()
        n = llm.calls
        b.cfg.llm_rpm, b.cfg.llm_auto_rpm = 5, 4
        assert b.wants_drafting()
        b.refill_from_catalog()
        assert not b.queue.pending() and b.state.prefill and llm.calls == n + 1  # one paced request re-pre-drafts
        assert old
        b.stopped = True


def test_state_atomic_and_tolerant(tmp_path):
    p = tmp_path / "state.json"
    s = BotState(p); s.liked = ["1"]; s.save()
    assert not (tmp_path / "state.json.tmp").exists() and BotState(p).liked == ["1"]
    p.write_text('{"seen": [1, 2')  # torn file
    assert BotState(p).seen == []  # no crash
