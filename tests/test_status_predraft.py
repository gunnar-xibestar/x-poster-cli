from xbot.commands import parse
from xbot.llm import FakeLLM, LLMFatal
from xbot.render import status_markup
from tests.test_search import P, S


def test_status_active_only_when_grok_connected_and_predrafting(mk):
    b = mk(FakeLLM(["hi"] * 5), search=[P(1)], **S())
    assert b.status_word() == "ACTIVE" and "ACTIVE" in status_markup(b) and b.status().startswith("ACTIVE")
    b.handle(parse("/pause")); assert b.status_word() == "PAUSED" and "PAUSED" in status_markup(b)
    assert b.tick() == 0 and b.ticks == 1 and b.found and not b.state.prefill  # polling continues, no pre-drafts
    b.handle(parse("/resume")); assert b.status_word() == "ACTIVE"
    b.tick(); assert b.state.prefill and b.queue.pending() == []  # pre-drafted, never auto-queued
    b.llm = None; assert b.status_word() == "PAUSED"  # Grok not connected


def test_status_paused_without_grok_and_after_fatal(mk):
    assert mk(xonly=True).status_word() == "PAUSED"
    b = mk(FakeLLM(fail=LLMFatal("bad key")), search=[P(1)], **S())
    b.tick(); assert b.paused and b.status_word() == "PAUSED"


def test_g_manual_draft_works_while_predrafting_paused(mk):
    llm = FakeLLM(["manual"])
    b = mk(llm, search=[P(1)], **S())
    b.handle(parse("/pause")); b.tick()
    assert b.draft_for_post(1) == "manual" and len(llm.calls) == 1

