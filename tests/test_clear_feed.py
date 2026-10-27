from xbot.app import XBotApp
from xbot.commands import parse
from tests.test_search import S
from tests.test_media_layout import P


async def test_bare_clear_wipes_feed_only(mk):
    b = mk(search=[P(i, f"post {i}") for i in range(1, 4)], **S(max_pending=2))
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 40)) as pilot:
        b.tick(); await pilot.pause()
        feed = app.query_one("#feed")
        assert feed.lines
        pend, found, seen = len(b.queue.pending()), len(b.found), list(b.state.seen)
        app._run("/clear"); await pilot.pause(); await pilot.pause()
        assert not feed.lines and len(b.queue.pending()) == pend and len(b.found) == found and b.state.seen == seen
        app.refresh_ui(); await pilot.pause()
        assert not feed.lines  # not re-shown
        b.dry_x.fake_search = [P(9, "brand new")]
        b.tick(force_search=True); await pilot.pause()
        assert any("brand new" in l.text for l in feed.lines)
        b.stopped = True


def test_clear_parse_forms():
    assert parse("/clear").args == ["feed"]
    assert parse("/clear suggested").args == ["search"] and parse("/clear mentions").args == ["mention"]


async def test_bare_clear_pauses_drafting_until_f5_and_g_still_works(mk):
    from tests.test_round_drafting import JsonLLM
    from xbot.render import drafts_title
    llm = JsonLLM()
    b = mk(llm, search=[P(i, f"post {i}") for i in range(1, 9)], draft_batch=8, prefill_max=2, **S(max_pending=2))
    notes = []
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 40)) as pilot:
        app.notify = lambda m, **k: notes.append(m)
        b.tick(); await pilot.pause()
        b.queue.reject(b.queue.pending()[0].id)  # a free slot
        app._run("/clear"); await pilot.pause()
        assert "feed cleared · drafting paused until F5" in notes and "drafting paused" in drafts_title(b)
        n = llm.calls
        assert not b.wants_drafting() and b.schedule_drafts() == 0 and b.refill_from_catalog() <= 1 and llm.calls == n
        b.tick(); assert llm.calls == n  # background ticks don't draft either
        assert b._draft("manual prompt", manual=True) is not None and llm.calls == n + 1  # g still calls Grok
        await pilot.press("f5"); await pilot.pause(); await pilot.pause()
        assert not b.drafting_hold and "drafting paused" not in drafts_title(b)
        b.stopped = True
