import pytest
from xbot.config import Config
from xbot.log import ActionLog
from xbot.llm import FakeLLM
from xbot.xapi import DryRunX
from xbot.bot import Bot

@pytest.fixture(autouse=True)
def no_x_keys(monkeypatch):
    for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET", "XAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def mk(tmp_path):
    def _mk(llm=None, mentions=None, search=None, clock=None, xonly=False, llm_factory=None, **cfg):
        cfg.setdefault("llm_rpm", 0)  # legacy tests assume unpaced Grok; pacing tests opt in
        cfg.setdefault("llm_auto_rpm", 0)
        cfg.setdefault("draft_batch_migrated", True)  # tests set draft_batch explicitly
        cfg.setdefault("draft_batch", 1)  # legacy tests count one Grok call per post
        c = Config(**cfg)
        feed = []
        log = ActionLog(tmp_path, sink=feed.append)
        b = Bot(c, None if xonly else (llm or FakeLLM()), DryRunX(mentions, search), log, clock=clock,
                llm_factory=llm_factory)
        b.author_fetch = lambda tid: None  # never hit the network in tests
        b.feed = feed
        return b
    return _mk


@pytest.fixture(autouse=True)
def no_real_browser(monkeypatch):
    """Never launch a real browser from tests."""
    import xbot.opener as op
    monkeypatch.setattr(op, "open_url_async", lambda url, done: done(None))
    import xbot.app as ap
    if hasattr(ap, "open_url_async"):
        monkeypatch.setattr(ap, "open_url_async", lambda url, done: done(None))


def queue_predrafts(b):
    """Simulate the user saving each Grok pre-draft to the queue (g + Ctrl+E): auto drafts never
    populate the queue on their own any more. Oldest first, mentions before search. Returns count."""
    n = 0
    for p in sorted(b.found, key=lambda p: (p.get("source") != "mention", int(p["id"]))):
        t = b.state.prefill.pop(str(p["id"]), None)
        if t:
            who = p.get("username") or p.get("author_id", "?")
            b._enqueue("reply", t, in_reply_to=p["id"], source="mention" if p.get("source") == "mention" else "search",
                       context=p["text"] if p.get("source") == "mention" else f"@{who}: {p['text']}",
                       conversation_id=p.get("conversation_id") or p["id"])
            n += 1
    b.state.save()
    return n
