from xbot.llm import FakeLLM
from xbot.config import Config


class Clock:
    t = 1000.0
    def __call__(self): return self.t


class Counting(FakeLLM):
    def __init__(self):
        super().__init__(["r"]); self.calls = 0
    def complete(self, *a, **k):
        self.calls += 1; return f"reply {self.calls}"


PACED = dict(llm_rpm=2, llm_auto_rpm=1)  # the shipped defaults


def _ments(n):
    return [{"id": str(10 + i), "text": f"@me q{i}"} for i in range(n)]


def test_defaults_5_total_4_auto():
    c = Config(); assert c.llm_rpm == 5 and c.llm_auto_rpm == 4


def test_auto_paced_1_per_minute_and_resumes(mk):
    clk, llm = Clock(), Counting()
    b = mk(llm, _ments(4), clock=clk, post_every_n_ticks=0, **PACED)
    b.tick()
    assert llm.calls == 1 and len(b.state.prefill) == 1 and not b.mention_pending()
    assert 0 < b.rate_limited() <= 60 and "paced" in (b.last_draft_error or "")
    clk.t += 30; b.refill_from_catalog(); b.tick()
    assert llm.calls == 1  # still inside the window: no extra auto call
    clk.t += 31
    assert b.retry_due()
    b.tick()
    assert llm.calls == 2 and len(b.state.prefill) == 2


def test_window_never_exceeds_rpm(mk):
    clk, llm = Clock(), Counting()
    b = mk(llm, _ments(4), clock=clk, post_every_n_ticks=0, max_mention_drafts=0, **PACED)
    stamps = []
    orig = llm.complete
    llm.complete = lambda *a, **k: (stamps.append(clk.t), orig(*a, **k))[1]
    for _ in range(40):
        b.tick(); clk.t += 5
    assert stamps and all(sum(1 for s in stamps if t <= s < t + 60) <= 1 for t in stamps)


def test_zero_disables_pacing(mk):
    clk, llm = Clock(), Counting()
    b = mk(llm, _ments(4), clock=clk, post_every_n_ticks=0, llm_rpm=0, llm_auto_rpm=0)
    b.tick()
    assert llm.calls == 4


def test_manual_g_never_blocked_by_auto(mk):
    clk, llm = Clock(), Counting()
    b = mk(llm, _ments(4), clock=clk, post_every_n_ticks=0, **PACED)
    b.tick()
    assert llm.calls == 1 and b.rate_limited() > 0
    assert b.rate_limited(manual=True) == 0
    assert b.draft_for_post(4)  # manual slot still free (#4 has no pre-draft yet)
    assert llm.calls == 2
    waited = []
    b.sleep = lambda s: (waited.append(s), setattr(clk, "t", clk.t + s))
    assert b.draft_for_post(4) and waited and 0 < waited[0] <= 61  # g waits for the slot, never refused
    assert llm.calls == 3
    clk.t += 61
    assert b.draft_for_post(4)


def test_configurable_limits(mk):
    clk, llm = Clock(), Counting()
    b = mk(llm, _ments(6), clock=clk, post_every_n_ticks=0, max_mention_drafts=0, llm_rpm=5, llm_auto_rpm=3)
    b.tick(); assert llm.calls == 3
    assert b.auto_limit() == 3
    b.cfg.llm_auto_rpm = 9; assert b.auto_limit() == 4  # always keeps one slot for g


def test_rpm_1_auto_waits_for_manual_g_and_never_exceeds(mk):
    clk, llm = Clock(), Counting()
    b = mk(llm, _ments(3), clock=clk, post_every_n_ticks=0, llm_rpm=1, llm_auto_rpm=1)
    assert b.auto_limit() == 1
    assert b._draft("x", manual=True)  # manual g first
    b.tick(); assert llm.calls == 1  # auto waits, no 429
    assert b.rate_limited() > 0
    clk.t += 61; b.tick(); assert llm.calls == 2  # auto ~1/min afterwards
    clk.t += 10; b.tick(); assert llm.calls == 2


def test_clamps(mk):
    b = mk(Counting(), llm_rpm=1, llm_auto_rpm=5); assert b.auto_limit() == 1
    b.cfg.llm_rpm = -3; b.cfg.llm_auto_rpm = 0; assert b._rpm() == 0 and b.auto_limit() == 0
    b.cfg.llm_rpm = 2; b.cfg.llm_auto_rpm = 9; assert b.auto_limit() == 1


def test_startup_and_f5_populate_with_defaults(mk):
    from xbot.commands import parse
    from tests.test_search import P as SP
    clk, llm = Clock(), Counting()
    b = mk(llm, _ments(2), search=[SP(i, text=f"linux {i}") for i in range(1, 9)], clock=clk, post_every_n_ticks=0,
           llm_rpm=5, llm_auto_rpm=4)
    assert b.tick(True) == 4 and len(b.state.prefill) == 4 and not b.queue.pending()  # startup: 4 pre-drafts right away
    b.handle(parse("/tick"))  # F5 in the same minute: says why nothing new
    assert any("waiting; next pre-draft in" in l for l in b.feed)
    clk.t += 61; b.handle(parse("/tick"))
    assert len(b.state.prefill) > 4 and not b.queue.pending()


def test_manual_wait_never_reports_0s(mk):
    clk, llm = Clock(), Counting()
    b = mk(llm, _ments(1), clock=clk, post_every_n_ticks=0, llm_rpm=1, llm_auto_rpm=1)
    b.tick()
    clk.t += 59.6  # 0.4 s left: rounding used to say "try again in 0s" and refuse
    b.sleep = lambda s: setattr(clk, "t", clk.t + s)
    assert b.draft_for_post(1) and "0s" not in (b.last_draft_error or "")


def test_429_message_uses_current_settings(mk):
    from xbot.llm import LLMRateLimited
    class R(FakeLLM):
        def complete(self, *a, **k): raise LLMRateLimited("429", 30)
    b = mk(R(["x"]), _ments(1), post_every_n_ticks=0, llm_rpm=5, llm_auto_rpm=4)
    b.tick()
    w = [l for l in b.feed if "xAI 429" in l]
    assert len(w) == 1 and "llm_rpm=5 (auto 4/min)" in w[0] and "\n" not in w[0]
