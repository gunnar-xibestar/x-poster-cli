import json
from xbot.commands import parse
from xbot.llm import FakeLLM
from xbot.queue import DraftQueue
from xbot.state import BotState

P = lambda i, text="Rust 2.0 is out", author="a1", conv=None: {
    "id": str(i), "text": text, "author_id": author, "username": f"u{author}", "conversation_id": conv or str(i)}


def S(**kw):
    kw = {"post_every_n_ticks": 0, "search_every_n_ticks": 1, **kw}
    return kw


def _S_old(**kw):
    return dict(post_every_n_ticks=0, search_every_n_ticks=1, **kw)


def test_search_drafts_reply_with_author_context(mk):
    llm = FakeLLM(["nice release"])
    b = mk(llm, search=[P(1)], **S())
    assert b.tick() == 1
    d = b.queue.pending()[0]
    assert d.source == "search" and d.in_reply_to == "1" and "@ua1" in llm.calls[0][1]
    assert b.dry_x.searches == [b.effective_query()[0]] and b.dry_x.sent == []


def test_skip_and_dedupe_and_own_posts(mk):
    b = mk(FakeLLM(["SKIP", "good reply"]), search=[P(1), P(2), P(3, author="dryrun-user")], **S())
    assert b.tick() == 1
    assert [d.in_reply_to for d in b.queue.pending()] == ["2"]
    b.dry_x.fake_search = [P(2)]; assert b.tick() == 0  # seen


def test_replied_thread_skipped(mk):
    b = mk(FakeLLM(), search=[P(1, conv="c9")], **S())
    b.tick(); b.handle(parse(f"/approve @{b.queue.pending()[0].id}"))
    b.dry_x.fake_search = [P(5, conv="c9")]; assert b.tick() == 0


def test_hourly_limit_counts_sends_not_drafts(mk):
    b = mk(FakeLLM(), search=[P(i) for i in range(1, 10)], **S(max_replies_per_hour=3, max_pending=10))
    assert b.tick() == 9  # drafting is not limited by max_replies_per_hour
    assert b.state.reply_sends_last_hour() == 0


def test_queue_cap_stops_drafting(mk):
    b = mk(FakeLLM(), search=[P(i) for i in range(1, 30)], **S(max_pending=10, max_replies_per_hour=100, search_max_results=30))
    b.tick()
    assert len(b.queue.pending()) == 10 and "FULL" in b.status()
    assert any("queue full" in f for f in b.feed)
    n = len(b.feed); assert b.tick() == 0 and sum("queue full" in f for f in b.feed[n:]) == 0  # logged once
    b.handle(parse(f"/reject @{b.queue.pending()[0].id}"))  # freed slot: background worker refills from the catalog
    b.refill_from_catalog()
    assert len(b.queue.pending()) == 10 and b.queue.pending()[-1].in_reply_to == "11"


def test_search_commands(mk):
    b = mk()
    b.handle(parse("/search linux kernel")); assert b.cfg.search_query == "linux kernel"
    b.handle(parse("/searchoff")); assert not b.cfg.search_enabled
    b.handle(parse("/searchon")); b.handle(parse("/maxresults 20")); assert b.cfg.search_max_results == 20
    b.handle(parse("/maxpending 3")); assert b.cfg.max_pending == 3


def test_url_warning(mk):
    b = mk(FakeLLM(["see https://example.com"]), search=[P(1)], **S())
    b.tick(); assert any("contains a URL" in f for f in b.feed)


def test_daily_cap_blocks_live_send(mk):
    sent = []
    class R:
        def post(self, text, in_reply_to=None): sent.append(text); return "1"
        def mentions(self, s=None): return []
        def search_recent(self, *a, **k): return []
        def me(self): return "me"
    b = mk(daily_cap_usd=0.02); b.real_x_factory = R
    b.handle(parse("/dryrun off"))
    for t in ("one", "two"):
        b.handle(parse(f"/post {t}")); b.handle(parse(f"/approve @{b.queue.pending()[-1].id}"))
    assert sent == ["one", "two"]  # 0.015 then 0.03 >= cap
    b.handle(parse("/post three")); b.handle(parse(f"/approve @{b.queue.pending()[-1].id}"))
    assert sent == ["one", "two"] and "CAP HIT" in b.status()


def test_queue_and_state_persist(tmp_path):
    q = DraftQueue(tmp_path / "q.json"); q.add("post", "hi"); q.add("reply", "yo", in_reply_to="1")
    q.reject(1)
    q2 = DraftQueue(tmp_path / "q.json")
    assert [d.text for d in q2.pending()] == ["yo"] and q2.add("post", "x").id == 3
    s = BotState(tmp_path / "s.json"); s.seen.append("5"); s.add_spend(0.5)
    s2 = BotState(tmp_path / "s.json"); assert s2.seen == ["5"] and s2.spent_today() == 0.5


def test_bot_reloads_queue(mk, tmp_path):
    b = mk(); b.handle(parse("/post persisted"))
    b2 = mk(); assert b2.queue.pending()[0].text == "persisted"
