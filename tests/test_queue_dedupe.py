"""Replying to a post any way deletes other queued replies to the same post (id, or author + post date)."""
from xbot.commands import parse
from xbot.llm import FakeLLM
from tests.test_search import P, S


def _b(mk):
    posts = [dict(P(1), created_at="2026-10-01T10:00:00Z"), dict(P(2, author="b2"), created_at="2026-10-02T10:00:00Z")]
    b = mk(FakeLLM(["x"] * 9), search=posts, **S()); b.tick(); b.state.prefill.clear()
    return b


def n_of(b, pid):
    return next(i for i, p in enumerate(b.found, 1) if p["id"] == pid)


def test_browser_reply_deletes_queued_for_same_post(mk):
    b = _b(mk)
    q1 = b.queue_reply_to_found(n_of(b, "1"), "queued 1"); q2 = b.queue_reply_to_found(n_of(b, "2"), "queued 2")
    b.browser_reply_to_found(n_of(b, "1"), "browser reply")
    ids = {d.id for d in b.queue.items}
    assert q1.id not in ids and q2.id in ids and any("removed queued reply for @ua1" in f for f in b.feed)


def test_send_reply_deletes_queued_on_success(mk):
    b = _b(mk)
    q = b.queue_reply_to_found(n_of(b, "1"), "queued")
    assert b.send_reply_to_found(n_of(b, "1"), "sent now")
    assert q.id not in {d.id for d in b.queue.items}


def test_match_by_author_and_date_when_id_differs(mk):
    b = _b(mk)
    q = b.queue_reply_to_found(n_of(b, "1"), "queued")
    q.post["id"] = "999"  # e.g. a different id for the same post copy
    other = {"id": "1", "username": "ua1", "created_at": "2026-10-01T10:00:00Z"}
    assert b.drop_queued_replies(other) == 1 and not b.queue.pending()
    q2 = b.queue_reply_to_found(n_of(b, "2"), "q2"); q2.post["id"] = "998"
    assert b.drop_queued_replies({"id": "5", "username": "ub2", "created_at": "2026-10-09T00:00:00Z"}) == 0  # date differs
    assert b.drop_queued_replies({"id": "5", "username": "zz", "created_at": "2026-10-02T10:00:00Z"}) == 0  # user differs


def test_approve_and_slash_reply_remove_other_queued(mk):
    b = _b(mk)
    a = b.queue_reply_to_found(n_of(b, "1"), "first"); c = b.queue_reply_to_found(n_of(b, "1"), "second")
    keep = b.queue_reply_to_found(n_of(b, "2"), "other post")
    b.opener = lambda url, done: done("test")
    b.handle(parse(f"/approve @{c.id}"))
    ids = {d.id for d in b.queue.items}
    assert a.id not in ids and c.id in ids and keep.id in ids
    b.handle(parse("/reply 2 replacement"))
    pend = [d for d in b.queue.pending() if d.in_reply_to == "2"]
    assert [d.text for d in pend] == ["replacement"]
