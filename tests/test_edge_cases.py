"""Edge cases from Net QA's review of 2451951."""
import json, os
import pytest
from xbot import config, llm as L
from xbot.commands import parse
from xbot.config import Config
from xbot.secure import write_private
from tests.test_feed_max import posts, shown
from tests.test_mention_cap import P
from tests.test_search import S


# ---- FIFO feed ------------------------------------------------------------------------------------
def test_f5_on_empty_fifo_searches_x(mk):
    b = mk(xonly=True); recs = []; b.log.rich_sink = recs.append
    calls = []; b.tick = lambda **k: calls.append(k) or 0
    assert b.replay_found() == 0 and b.feed_found() == [] and b.saved_left() == []
    b.handle(parse("/tick"))
    assert calls == [{"force_search": True}] and shown(recs) == []


def test_feed_max_zero_or_negative_means_no_cap(mk, monkeypatch):
    for v in (0, -5):
        monkeypatch.setattr(config, "FEED_MAX", v)
        b = mk(xonly=True); recs = []; b.log.rich_sink = recs.append
        b.found = posts(130); b.state.feed_shown = []
        b.replay_found()
        assert len(shown(recs)) == 130 and len(b.feed_found()) == 130 and b.saved_left() == []


def test_feedlog_max_posts_zero_never_trims():
    import asyncio
    from textual.app import App
    from xbot.app import FeedLog
    async def run():
        class A(App):
            def compose(self):
                yield FeedLog(id="feed")
        async with A().run_test() as pilot:
            f = pilot.app.query_one(FeedLog); f.max_posts = 0
            for i in range(5):
                f.write(f"p{i}", post=True)
            assert sum(f._posts) == 5
    asyncio.run(run())


@pytest.mark.parametrize("k,first_page,second", [(100, 100, 0), (101, 100, 1)])
def test_feed_max_boundary(mk, k, first_page, second):
    b = mk(xonly=True); recs = []; b.log.rich_sink = recs.append
    calls = []; b.tick = lambda **kw: calls.append(kw) or 0
    b.found = posts(k)
    b.replay_found()
    assert len(shown(recs)) == first_page == config.FEED_MAX
    recs.clear(); b.handle(parse("/tick"))
    assert len(shown(recs)) == second and bool(calls) == (second == 0)
    assert len(b.feed_found()) == 100


# ---- write_private --------------------------------------------------------------------------------
def test_write_private_failure_leaves_no_tmp(tmp_path, monkeypatch):
    p = tmp_path / "found.json"
    write_private(p, "old")
    def full(fd, data): raise OSError(28, "No space left on device")
    monkeypatch.setattr(os, "write", full)
    with pytest.raises(OSError):
        write_private(p, "new")
    monkeypatch.undo()
    assert p.read_text() == "old" and not list(tmp_path.glob("*.tmp"))


def test_write_private_replace_failure_leaves_no_tmp(tmp_path, monkeypatch):
    p = tmp_path / "state.json"
    monkeypatch.setattr(os, "replace", lambda a, b: (_ for _ in ()).throw(OSError(2, "gone")))
    with pytest.raises(OSError):
        write_private(p, "x")
    assert not list(tmp_path.glob("*.tmp"))


# ---- CLI help vs positional args --------------------------------------------------------------------
def test_help_word_as_positional_arg_is_not_top_level_help(monkeypatch, capsys):
    from xbot import app
    seen = []
    monkeypatch.setattr(app, "search_cli", lambda argv, **k: seen.append(argv) or 0)
    import xbot.secure as sec
    for name in ("install", "tighten", "load_secret_cmd"):
        monkeypatch.setattr(sec, name, lambda *a, **k: None)
    monkeypatch.setattr(sec, "env_file_problem", lambda *a, **k: None)
    with pytest.raises(SystemExit) as e:
        app.main(["search", "help"])
    assert e.value.code == 0 and seen == [["help"]] and "usage: xbot" not in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        app.main(["help", "search"])  # help first: top-level usage, nothing else runs
    assert e.value.code == 0 and "usage: xbot" in capsys.readouterr().out and seen == [["help"]]


# ---- Grok errors ----------------------------------------------------------------------------------
def _grok(monkeypatch, exc):
    monkeypatch.setenv("XAI_API_KEY", "test-key-not-real")
    g = L.GrokLLM("grok-4.7", "https://api.x.ai/v1")
    def boom(**k): raise exc
    monkeypatch.setattr(g.client.chat.completions, "create", boom)
    return g


def _status(code, body="err"):
    import openai
    from tests.test_grok_timeout import httpx
    req = httpx.Request("POST", "https://api.x.ai/v1/chat/completions")
    resp = httpx.Response(code, request=req, json={"error": body})
    cls = {401: openai.AuthenticationError, 500: openai.InternalServerError, 429: openai.RateLimitError}[code]
    return cls(body, response=resp, body={"error": body})


@pytest.mark.parametrize("code,kind", [(500, L.LLMError), (401, L.LLMFatal), (429, L.LLMRateLimited)])
def test_non_timeout_errors_are_not_timeouts(monkeypatch, code, kind):
    with pytest.raises(kind) as e:
        _grok(monkeypatch, _status(code)).complete("s", "u")
    assert not isinstance(e.value, L.LLMTimeout) and "timed out" not in str(e.value)


def test_retry_that_times_out_again_keeps_posts_waiting(mk):
    n = {"calls": 0}
    class Slow:
        last_cost_usd = 0.0
        def complete(self, s, u):
            n["calls"] += 1
            raise L.LLMTimeout("Grok timed out after 180s", 180)
    b = mk(Slow(), search=[P(i) for i in range(1, 6)], draft_batch=4, **S(max_pending=4))
    msgs = []; b.log.rich_sink = msgs.append
    b.tick()
    b.schedule_drafts()  # the retry on the next refresh: times out again
    warns = [r["msg"] for r in msgs if r.get("kind") == "warn" and "timed out" in r["msg"]]
    assert n["calls"] == 2 and len(warns) == 2
    assert not b._skipped and not b.state.prefill and not b.queue.pending() and b.catalog_size() >= 4


# ---- invalid stored draft_batch -------------------------------------------------------------------
@pytest.mark.parametrize("stored", [0, -3, "abc", None, 2.5])
def test_invalid_stored_draft_batch(tmp_path, mk, stored):
    (tmp_path / "config.json").write_text(json.dumps({"draft_batch": stored}))
    c = Config.load(tmp_path)
    assert isinstance(c.draft_batch, int)
    b = mk(xonly=True)
    b.cfg.draft_batch = stored  # even if a bad value reaches the bot: one post per request, no crash
    assert b._batch_n() >= 1
