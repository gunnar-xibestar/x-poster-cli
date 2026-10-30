from tests.test_round_drafting import JsonLLM
from tests.test_search import P, S

M = lambda i: {"id": str(i), "text": f"@me q{i}", "author_id": f"m{i}", "username": f"m{i}", "conversation_id": str(i)}


class KindLLM(JsonLLM):
    def __init__(self):
        super().__init__(); self.kinds = []
    def complete(self, system, user):
        self.kinds.append("mention" if ("mention us" in user or "mentions us" in user) else "search")
        return super().complete(system, user)


def mkb(mk, nm=6, ns=6, **kw):
    llm = KindLLM()
    kw = {**dict(draft_batch=2, prefill_max=4, max_mention_drafts=2, max_replies_per_hour=100, max_pending=2), **kw}
    b = mk(llm, mentions=[M(100 + i) for i in range(nm)], search=[P(10 + i) for i in range(ns)], **S(**kw))
    return b, llm


def test_alternates_on_ties_then_prefills_fairly(mk):
    b, llm = mkb(mk); b.tick()
    assert llm.kinds[:2] in (["mention", "search"], ["search", "mention"])
    assert b.queue.pending() == []  # nothing auto-queued
    pool = set(b.state.prefill)
    assert len(pool) == 4 and len(pool & {str(100 + i) for i in range(6)}) == 2  # shared half each
    n = llm.calls
    assert not b.wants_drafting() and b.refill_from_catalog() == 0 and llm.calls == n  # pool full: no request


def test_emptiest_queue_goes_first(mk):
    b, llm = mkb(mk, draft_batch=1, max_mention_drafts=4, max_pending=4)
    b._remember(M(100), "mention"); b._accept(M(100), "hi", "mention"); b._accept(M(101), "hi", "mention")
    for i in range(3):
        b._remember(P(10 + i), "search")
    b.schedule_drafts(max_requests=1)
    assert llm.kinds == ["search"]


def test_manual_slot_kept(mk):
    b, llm = mkb(mk, llm_rpm=5, llm_auto_rpm=5, nm=20, ns=20, prefill_max=40, max_mention_drafts=10)
    b.cfg.max_pending = 10; b.tick()
    assert llm.calls <= 4 and b.manual_wait() == 0
