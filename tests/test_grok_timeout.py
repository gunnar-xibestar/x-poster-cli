import openai, pytest
try:
    import httpx2 as httpx
except ImportError:  # older openai
    import httpx
from xbot import llm as L
from xbot.config import Config
from xbot.bot import Bot
from xbot.log import ActionLog
from xbot.xapi import DryRunX


def _grok(monkeypatch, exc, base="https://api.x.ai/v1"):
    monkeypatch.setenv("XAI_API_KEY", "test-key-not-real")
    g = L.GrokLLM("grok-4.7", base)
    def boom(**k): raise exc
    monkeypatch.setattr(g.client.chat.completions, "create", boom)
    return g


REQ = httpx.Request("POST", "https://api.x.ai/v1/chat/completions")


def test_client_timeout_is_180(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key-not-real")
    assert L.GROK_TIMEOUT_S == 180 and L.GrokLLM("grok-4.7", "https://api.x.ai/v1").client.timeout == 180


def test_timeout_is_llmtimeout(monkeypatch):
    with pytest.raises(L.LLMTimeout) as e:
        _grok(monkeypatch, openai.APITimeoutError(request=REQ)).complete("s", "u")
    assert "timed out after 180s" in str(e.value)


def test_httpx_timeout_cause_is_llmtimeout(monkeypatch):
    err = openai.APIConnectionError(request=REQ)
    class ReadTimeout(Exception): pass
    err.__cause__ = ReadTimeout("slow")
    with pytest.raises(L.LLMTimeout):
        _grok(monkeypatch, err).complete("s", "u")


def test_connection_error_message(monkeypatch):
    with pytest.raises(L.LLMError) as e:
        _grok(monkeypatch, openai.APIConnectionError(request=REQ)).complete("s", "u")
    assert not isinstance(e.value, L.LLMTimeout) and "proxy" not in str(e.value) and "network error" in str(e.value)
    with pytest.raises(L.LLMError) as e:
        _grok(monkeypatch, openai.APIConnectionError(request=REQ), "http://127.0.0.1:8767/v1").complete("s", "u")
    assert "local proxy down?" in str(e.value)


def test_batch_timeout_message_and_posts_retried(mk):
    from tests.test_search import S
    from tests.test_mention_cap import P
    class Slow:
        last_cost_usd = 0.0
        def complete(self, s, u):
            raise L.LLMTimeout("Grok timed out after 180s", 180)
    b = mk(Slow(), search=[P(i) for i in range(1, 6)], draft_batch=4, **S(max_pending=4))
    msgs = []; b.log.rich_sink = msgs.append
    b.tick()
    warn = [r["msg"] for r in msgs if r.get("kind") == "warn" and "timed out" in r["msg"]]
    assert warn and warn[0] == "Grok timed out after 180s drafting 4 posts; will retry next refresh"
    assert not b._skipped and not b.state.prefill and not b.queue.pending()
    assert b.catalog_size() >= 4  # still waiting: drafted on a later refresh


@pytest.mark.parametrize("old,new", [(8, 4), (1, 1)])
def test_draft_batch_migration(tmp_path, old, new):
    saved = []
    c = Config(draft_batch=old)
    Bot(c, None, DryRunX(), ActionLog(tmp_path, sink=lambda *a: None), state_dir=tmp_path, save_config=lambda: saved.append(1))
    assert c.draft_batch == new and c.draft_batch_migrated and saved
    c.draft_batch = 8  # set again after the migration: kept
    Bot(c, None, DryRunX(), ActionLog(tmp_path, sink=lambda *a: None), state_dir=tmp_path, save_config=lambda: None)
    assert c.draft_batch == 8
