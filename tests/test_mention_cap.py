from xbot.config import Config
from xbot.commands import parse
from xbot.llm import FakeLLM

M = lambda i: {"id": str(i), "text": f"@me q{i}", "author_id": f"m{i}", "username": f"m{i}", "conversation_id": str(i)}


def test_mentions_predrafted_never_auto_queued(mk):
    b = mk(FakeLLM(["hi"] * 50), mentions=[M(i) for i in range(1, 14)], post_every_n_ticks=0,
           search_enabled=False, max_replies_per_hour=100, max_mention_drafts=10, prefill_max=20)
    assert Config().max_mention_drafts == 4 and Config().max_pending == 4
    b.tick()
    assert b.queue.pending() == []  # auto drafts no longer populate the queue
    assert sorted(int(k) for k in b.state.prefill) == list(range(1, 14))  # Grok pre-drafted every mention
    assert len([p for p in b.found if p["source"] == "mention"]) == 13


def P(i):
    return {"id": str(i), "text": f"Rust tip {i}", "author_id": f"s{i}", "username": f"s{i}", "conversation_id": str(i)}


def test_clear_commands_on_manually_queued(mk):
    from tests.conftest import queue_predrafts
    b = mk(FakeLLM(["hi"] * 200), mentions=[M(i) for i in range(1, 4)], search=[P(i) for i in range(100, 103)],
           post_every_n_ticks=0, search_every_n_ticks=1, max_replies_per_hour=100, max_pending=10, max_mention_drafts=10)
    b.handle(parse("/tick")); assert b.queue.pending() == [] and queue_predrafts(b) == 6
    calls = len(b.dry_x.searches)
    b.handle(parse("/clear suggested"))
    assert sum(d.source == "search" for d in b.queue.pending()) == 0 and sum(d.source == "mention" for d in b.queue.pending()) == 3
    b.refill_from_catalog(); assert sum(d.source == "search" for d in b.queue.pending()) == 0  # never auto-refilled
    b.handle(parse("/clear mentions")); assert b.queue.pending() == [] and len(b.dry_x.searches) == calls


def test_xonly_catalog_drafted_when_grok_turns_on(mk):
    b = mk(xonly=True, mentions=[M(i) for i in range(1, 4)], search=[P(i) for i in range(100, 105)],
           post_every_n_ticks=0, search_every_n_ticks=1, max_replies_per_hour=100, max_pending=10,
           llm_factory=lambda: FakeLLM(["hi"] * 50))
    b.handle(parse("/tick"))
    assert b.queue.pending() == [] and len(b.found) == 8
    b.llm = b.llm_factory(); b.refill_from_catalog()  # Grok connected (e.g. after restart with a key)
    assert b.queue.pending() == [] and len(b.state.prefill) == 8 and b.status_word() == "ACTIVE"


async def test_queue_clear_keys_confirm(mk):
    from xbot.app import XBotApp, Confirm
    b = mk(FakeLLM(["hi"] * 20), mentions=[M(1), M(2)], search=[P(100)], post_every_n_ticks=0, search_every_n_ticks=1)
    b.tick(); from tests.conftest import queue_predrafts; queue_predrafts(b)
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app.query_one("#queue").focus(); await pilot.pause()
        await pilot.press("x"); await pilot.pause(); assert isinstance(app.screen, Confirm)
        await pilot.press("n"); await pilot.pause()
        assert len(b.queue.pending()) == 3
        await pilot.press("x"); await pilot.pause(); await pilot.press("y"); await pilot.pause()
        assert [d.source for d in b.queue.pending()] == ["mention", "mention"]
        await pilot.press("X"); await pilot.pause(); await pilot.press("y"); await pilot.pause()
        assert b.queue.pending() == []


async def test_f5_runs_tick_while_typing(mk):
    from xbot.app import XBotApp
    b = mk(FakeLLM(["hi"] * 5), mentions=[M(1)], search_enabled=False, post_every_n_ticks=0)
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app.query_one("#cmd").focus(); await pilot.pause()
        await pilot.press("f5"); await pilot.pause()
        assert b.ticks == 1 and b.queue.pending() == [] and list(b.state.prefill) == ["1"]


async def test_panel_headers_show_shown_and_waiting(mk):
    from xbot.app import XBotApp
    b = mk(FakeLLM(["hi"] * 50), mentions=[M(i) for i in range(1, 13)], search=[P(i) for i in range(100, 115)],
           post_every_n_ticks=0, search_every_n_ticks=1, max_replies_per_hour=100, search_max_results=15, max_pending=10, max_mention_drafts=10, prefill_max=27)
    b.tick(); from tests.conftest import queue_predrafts
    for d in queue_predrafts(b) and [d for d in b.queue.pending() if d.source == "mention"][10:]: b.queue.reject(d.id)
    for d in [d for d in b.queue.pending() if d.source == "search"][10:]: b.queue.reject(d.id)
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(160, 60)) as pilot:
        await pilot.pause()
        txt = " ".join(str(l.render()) for l in app.query("#queue .qhdr Label"))
        assert "Mentions (10" in txt and "Suggested replies (10" in txt
