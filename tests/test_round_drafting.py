from xbot.app import XBotApp, PostCard
from xbot.bot import Bot
from xbot.llm import FakeLLM
from xbot.render import drafts_title
from tests.test_search import P, S
from tests.test_card_open import rich_post


class JsonLLM(FakeLLM):
    def __init__(self, fmt=True):
        super().__init__(["x"]); self.calls = 0; self.fmt = fmt
    def complete(self, system, user):
        self.calls += 1
        if not self.fmt:
            return f"plain {self.calls}"
        import re
        ids = re.findall(r"^\[(\d+)\]", user, re.M)
        return "```json\n[" + ",".join(f'{{"id": "{i}", "reply": "{"SKIP" if i == "2" else "nice " + i}"}}' for i in ids) + "]\n```"


def test_batch_one_request_for_four_posts(mk):
    llm = JsonLLM()
    b = mk(llm, search=[P(i) for i in range(1, 6)], draft_batch=4, **S(max_pending=10)); b.tick()
    texts = [d.text for d in b.queue.pending()]
    assert "nice 1" in texts and "nice 5" in texts and not any("SKIP" in t for t in texts)
    assert llm.calls == 2  # 4 + 1 posts


def test_batch_falls_back_when_not_json(mk):
    llm = JsonLLM(fmt=False)
    b = mk(llm, search=[P(i) for i in range(1, 4)], draft_batch=4, **S(max_pending=10)); b.tick()
    assert len(b.queue.pending()) == 3


def test_parse_batch_rejects_junk():
    assert Bot.parse_batch("no json", {"1"}) is None
    assert Bot.parse_batch('[{"id": "9", "reply": "x"}]', {"1"}) is None
    assert Bot.parse_batch('[{"id": 1, "reply": "hi"}]', {"1"}) == {"1": "hi"}


def test_skip_prompt_prefers_drafting():
    assert "only if" in Bot.SKIP_RULE and "always write" in Bot.SKIP_RULE


def test_success_clears_stale_backoff(mk):
    b = mk(FakeLLM(), search=[P(1)], **S()); b.llm_backoff_until = 0.0
    b.llm_backoff_until = -1.0  # stale (past) value
    b.tick(); assert b.llm_backoff_until == 0.0


def test_reply_limit_on_live_sends(mk):
    b = mk(FakeLLM(), **S(max_replies_per_hour=1)); b.cfg.dry_run = False
    class RX:
        def post(self, text, in_reply_to=None): return "77"
    b.real_x = RX()
    assert b.send("reply", "a", in_reply_to="1") is not None
    assert b.state.reply_sends_last_hour() == 1
    assert b.send("reply", "b", in_reply_to="2") is None


def test_wants_drafting_and_title(mk):
    b = mk(xonly=True, search=[P(i) for i in range(1, 4)], **S(max_pending=10)); b.tick()
    b.llm = FakeLLM(["r"])
    assert b.wants_drafting() and "drafting" in drafts_title(b)
    b.paused = True; assert not b.wants_drafting() and "drafting" not in drafts_title(b)


async def test_background_worker_fills_without_f5(mk):
    b = mk(xonly=True, search=[P(i) for i in range(1, 4)], **S(max_pending=10)); b.tick()
    assert not b.queue.pending()
    b.llm = FakeLLM(["hello"])
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 40)) as pilot:
        app.run_worker(app.loop()); await pilot.pause(2.5)
        assert len(b.queue.pending()) == 3
        b.stopped = True


async def test_like_key_uses_api_not_browser(mk):
    b = mk(xonly=True, search=[rich_post(5)], **S()); b.tick()
    opened, liked = [], []
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 40)) as pilot:
        b.opener = lambda url, done: (opened.append(url), done("test"))
        b.like_post = lambda n: (liked.append(n), (True, f"liked #{n}"))[1]
        app.action_show_post(1); await pilot.pause()
        assert isinstance(app.screen, PostCard)
        await pilot.press("l"); await pilot.pause(); await pilot.pause()
        assert liked == [1] and opened == []
        b.stopped = True


def test_fill_then_prefill_one_request(mk):
    llm = JsonLLM()
    b = mk(llm, search=[P(i) for i in range(1, 8)], draft_batch=8, prefill_max=20, **S(max_pending=2)); b.tick()
    assert llm.calls == 1 and len(b.queue.pending()) == 2
    assert set(b.state.prefill) == {"4", "5", "6", "7"}  # 1,3 queued; 2 was SKIP
    assert "prefilled 4" in drafts_title(b) and "drafts full" in drafts_title(b)


def test_everything_full_makes_no_llm_call(mk):
    llm = JsonLLM()
    b = mk(llm, search=[P(i) for i in range(1, 8)], draft_batch=8, prefill_max=20, **S(max_pending=2)); b.tick()
    n = llm.calls
    assert not b.wants_drafting()
    assert b.refill_from_catalog() == 0 and llm.calls == n


def test_prefill_cap_stops_requests(mk):
    llm = JsonLLM()
    b = mk(llm, search=[P(i) for i in range(10, 30)], draft_batch=8, prefill_max=3, **S(max_pending=1)); b.tick()
    assert len(b.state.prefill) == 3 and not b.wants_drafting()
    n = llm.calls; b.refill_from_catalog(); assert llm.calls == n


def test_freed_slot_promotes_without_api(mk):
    from xbot.commands import parse
    llm = JsonLLM()
    b = mk(llm, search=[P(i) for i in range(3, 8)], draft_batch=8, **S(max_pending=2)); b.tick()
    n = llm.calls; first = b.queue.pending()[0]
    b.handle(parse(f"/reject @{first.id}"))
    assert llm.calls == n and len(b.queue.pending()) == 2 and "5" not in b.state.prefill


def test_prefill_persists_and_g_uses_it(mk, tmp_path):
    from xbot.state import BotState
    llm = JsonLLM()
    b = mk(llm, search=[P(i) for i in range(3, 6)], draft_batch=8, **S(max_pending=1)); b.tick()
    if b.state.path:
        assert BotState(b.state.path).prefill == b.state.prefill and b.state.prefill
    n = llm.calls
    k = next(i for i, p in enumerate(b.found, 1) if str(p["id"]) == "4")
    assert b.draft_for_post(k) == "nice 4" and llm.calls == n


def test_hidden_post_drops_prefill(mk):
    llm = JsonLLM()
    b = mk(llm, search=[P(i) for i in range(3, 6)], draft_batch=8, **S(max_pending=1)); b.tick()
    k = next(i for i, p in enumerate(b.found, 1) if str(p["id"]) == "4")
    b.hide_post(k); assert "4" not in b.state.prefill
