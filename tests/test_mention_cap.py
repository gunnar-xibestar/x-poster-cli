from xbot.config import Config
from xbot.commands import parse
from xbot.llm import FakeLLM
from xbot.render import drafts_title

M = lambda i: {"id": str(i), "text": f"@me q{i}", "author_id": f"m{i}", "username": f"m{i}", "conversation_id": str(i)}


def test_mention_drafts_capped_and_refilled(mk):
    b = mk(FakeLLM(["hi"] * 50), mentions=[M(i) for i in range(1, 14)], post_every_n_ticks=0,
           search_enabled=False, max_replies_per_hour=100, max_mention_drafts=10)
    assert b.cfg.max_mention_drafts == 10 and Config().max_mention_drafts == 4 and Config().max_pending == 4
    b.tick()
    ments = [d for d in b.queue.pending() if d.source == "mention"]
    assert len(ments) == 10 and sorted(int(d.in_reply_to) for d in ments) == list(range(1, 11))
    assert len([p for p in b.found if p["source"] == "mention"]) == 13  # extras still in the feed
    assert len(b.mentions_waiting()) == 3
    assert "10/10 mentions" in drafts_title(b) and "waiting=3" in b.status() and "waiting 3" in drafts_title(b)
    b.queue.reject(ments[0].id)
    b.tick()
    ids = {d.in_reply_to for d in b.queue.pending() if d.source == "mention"}
    assert "11" in ids and "1" not in ids and len(ids) == 10  # rejected one is not redrafted
    b.handle(parse("/maxmentions 0")); b.tick()
    assert len([d for d in b.queue.pending() if d.source == "mention"]) == 12 and not b.mentions_waiting()


def P(i):
    return {"id": str(i), "text": f"Rust tip {i}", "author_id": f"s{i}", "username": f"s{i}", "conversation_id": str(i)}


def test_catalog_fills_freed_slots_without_fetch(mk):
    b = mk(FakeLLM(["hi"] * 200), mentions=[M(i) for i in range(1, 14)], search=[P(i) for i in range(100, 125)],
           post_every_n_ticks=0, search_every_n_ticks=1, max_replies_per_hour=100, search_max_results=25, max_pending=10, max_mention_drafts=10)
    b.handle(parse("/tick"))
    pend = b.queue.pending()
    assert sum(d.source == "mention" for d in pend) == 10 and sum(d.source == "search" for d in pend) == 10
    assert len([p for p in b.found if p["source"] == "search"]) == 25  # all fetched posts are in the feed/catalog
    calls = len(b.dry_x.searches)
    for d in [d for d in pend if d.source == "mention"][:2] + [d for d in pend if d.source == "search"][:3]:
        b.handle(parse(f"/reject @{d.id}"))
    b.refill_from_catalog()  # the app's background worker does this (reject itself never calls Grok)
    pend = b.queue.pending()
    assert sum(d.source == "mention" for d in pend) == 10 and sum(d.source == "search" for d in pend) == 10
    assert len(b.dry_x.searches) == calls  # drawn from the catalog, no new fetch
    b.handle(parse("/clear suggested"))
    assert sum(d.source == "search" for d in b.queue.pending()) == 0  # not redrafted until slots refill
    assert sum(d.source == "mention" for d in b.queue.pending()) == 10
    b.handle(parse("/clear mentions")); assert b.queue.pending() == []


def test_xonly_catalog_drafted_when_grok_turns_on(mk):
    b = mk(xonly=True, mentions=[M(i) for i in range(1, 4)], search=[P(i) for i in range(100, 105)],
           post_every_n_ticks=0, search_every_n_ticks=1, max_replies_per_hour=100, max_pending=10,
           llm_factory=lambda: FakeLLM(["hi"] * 50))
    b.handle(parse("/tick"))
    assert b.queue.pending() == [] and len(b.found) == 8
    b.handle(parse("/grok on"))
    pend = b.queue.pending()
    assert sum(d.source == "mention" for d in pend) == 3 and sum(d.source == "search" for d in pend) == 5


async def test_queue_clear_keys_confirm(mk):
    from xbot.app import XBotApp, Confirm
    b = mk(FakeLLM(["hi"] * 20), mentions=[M(1), M(2)], search=[P(100)], post_every_n_ticks=0, search_every_n_ticks=1)
    b.tick()
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
        assert b.ticks == 1 and [d.in_reply_to for d in b.queue.pending()] == ["1"]


async def test_panel_headers_show_shown_and_waiting(mk):
    from xbot.app import XBotApp
    b = mk(FakeLLM(["hi"] * 50), mentions=[M(i) for i in range(1, 13)], search=[P(i) for i in range(100, 115)],
           post_every_n_ticks=0, search_every_n_ticks=1, max_replies_per_hour=100, search_max_results=15, max_pending=10, max_mention_drafts=10)
    b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(160, 60)) as pilot:
        await pilot.pause()
        txt = " ".join(str(l.render()) for l in app.query("#queue .qhdr Label"))
        assert "Mentions (10 shown · 2 waiting)" in txt and "Suggested replies (10 shown · 5 waiting)" in txt
