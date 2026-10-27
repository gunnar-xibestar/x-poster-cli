import json, pytest
from types import SimpleNamespace
from xbot import credits as K
from xbot.config import Config
from xbot.commands import parse, CommandError
from xbot.configcli import cli
from xbot.llm import FakeLLM
from xbot.state import BotState


def mk(tmp_path, limit=1.0, cost=0.4):
    from xbot.bot import Bot
    from xbot.log import ActionLog
    from xbot.xapi import DryRunX
    c = Config(); c.spend_limit = limit
    llm = FakeLLM(); llm.cost = cost
    b = Bot(c, llm, DryRunX([], []), ActionLog(sink=lambda *a: None), state_dir=tmp_path, save_config=lambda: None)
    return b, llm


def test_cost_ticks_and_tokens():
    assert K.cost_from_usage("grok-4.7", {"cost_in_usd_ticks": 25_000_000}) == pytest.approx(0.0025)
    u = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000, "prompt_tokens_details": {"cached_tokens": 0}}
    assert K.cost_from_usage("grok-4.7", u) == pytest.approx(8.0)


def test_no_request_at_or_over_limit_and_exit_resets(tmp_path):
    b, llm = mk(tmp_path)
    got = []; b.on_limit_exit = got.append
    for _ in range(5):
        b._draft("hi", manual=True)
    assert len(llm.calls) == 3  # 0.4, 0.8, 1.2 -> reached; nothing after
    assert got and "spend limit $1.00 reached" in got[0] and "reset to $0" in got[0] and "unchanged" in got[0]
    assert b.cfg.spend_limit == 1.0
    summ = b.end_session()
    assert summ.startswith("xbot session:") and "API spent $1.20 of $1.00 limit (X $0.00 + Grok $1.20)" in summ and "reached" in summ
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["grok_run_spend"] == 0.0 and sum(saved["grok_spend"].values()) == pytest.approx(1.2)


def test_already_at_limit_sends_nothing(tmp_path):
    b, llm = mk(tmp_path)
    b.state.grok_run_spend = 1.0
    assert b._draft("hi", manual=True) is None and llm.calls == [] and b.limit_exit


def test_startup_fresh_after_reset(tmp_path):
    b, _ = mk(tmp_path, cost=2.0); b._draft("x", manual=True)
    b2, llm2 = mk(tmp_path, cost=0.1)
    assert b2.state.grok_run_spend == 0.0 and b2._draft("x", manual=True) and len(llm2.calls) == 1


def test_limit_command(tmp_path):
    for raw in ("5", "$5", "5.00"):
        assert parse("/limit " + raw).args == [5.0]
    assert parse("/limit").args == []
    for bad in ("off", "0", "-1", "abc"):
        with pytest.raises(CommandError):
            parse("/limit " + bad)
    b, _ = mk(tmp_path); out = []
    b.log.event = lambda kind, m: out.append(m)
    b.handle(parse("/limit $7")); assert b.cfg.spend_limit == 7.0
    b.handle(parse("/limit")); assert "spend limit $7.00" in out[-1] and "left $7.00" in out[-1]


def test_config_cli(tmp_path):
    out = []
    assert cli(["spend_limit", "$3"], config_dir=tmp_path, out=out.append) == 0
    assert json.loads((tmp_path / "config.json").read_text())["spend_limit"] == 3.0
    for bad in ("off", "0"):
        assert cli(["spend_limit", bad], config_dir=tmp_path, out=out.append) == 2
    assert "always on" in out[-1]
    assert Config().spend_limit == 5.0
    assert cli(["credits_start_date", "nope"], config_dir=tmp_path, out=out.append) == 2


def test_spend_lines_and_balance(tmp_path):
    b, _ = mk(tmp_path)
    ls = K.spend_lines(b)
    assert ls[0].startswith("API $0.00 / $1.00 limit") and any("credits_start 25" in l for l in ls)
    b.cfg.credits_start = 25; b.state.grok_spend = {"2026-10-01": 1.5}
    assert any("est. credits left: $23.50" in l for l in K.spend_lines(b))
    b.credit_balance = (12.34, 0)
    assert any(l.startswith("credits: $12.34 (xAI, as of") for l in K.spend_lines(b))


def test_fetch_balance_no_key_leak():
    calls = []
    def get(url, key):
        calls.append(url)
        return {"team_id": "t1"} if url.endswith("/v1/api-key") else {"total": {"val": "-1234"}}
    env = {"XAI_MANAGEMENT_KEY": "mgmt-secret-xyz", "XAI_API_KEY": "api-secret-xyz"}
    assert K.fetch_balance(env, get) == (12.34, None)
    assert calls[1] == "https://management-api.x.ai/v1/billing/teams/t1/prepaid/balance"
    def boom(url, key): raise RuntimeError(key)
    usd, err = K.fetch_balance(env, boom)
    assert usd is None and "secret" not in err
    assert K.fetch_balance({}, get) == (None, None)


def test_app_limit_exit_saves_and_exits():
    from xbot.app import XBotApp
    ev = []
    fake = SimpleNamespace(is_running=False, shutdown=lambda: ev.append("shutdown"), exit=lambda: ev.append("exit"))
    XBotApp._limit_exit(fake, "xbot stopped: xAI spend limit $5.00 reached")
    assert ev == ["shutdown", "exit"] and fake._limit_msg.startswith("xbot stopped")


def test_session_resets_on_normal_exit_keeps_daily(tmp_path):
    t = [1000.0]
    b, _ = mk(tmp_path, limit=5, cost=0.42); b.session_start = t[0]; b.state.clock = lambda: t[0]
    b._draft("x", manual=True)
    assert K.spend_lines(b)[0] == "API $0.42 / $5.00 limit [dim](X $0.00 + Grok $0.42)[/] · 5d $0.42"
    t[0] += 3600 + 23 * 60
    assert b.end_session() == "xbot session: 1h 23m · API spent $0.42 of $5.00 limit (X $0.00 + Grok $0.42) · last 5 days $0.42"
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["grok_run_spend"] == 0 and sum(saved["grok_spend"].values()) == pytest.approx(0.42)


def test_start_always_at_zero(tmp_path):
    st = BotState(tmp_path / "state.json"); st.grok_run_spend = 3.0; st.save()  # e.g. killed with -9
    b, _ = mk(tmp_path)
    assert b.state.grok_run_spend == 0.0


def test_app_shutdown_ends_session(tmp_path):
    from xbot.app import XBotApp
    b, _ = mk(tmp_path, cost=0.5); b._draft("x", manual=True)
    fake = SimpleNamespace(bot=b)
    XBotApp.shutdown(fake)
    assert "API spent $0.50" in fake._session_line and b.state.grok_run_spend == 0


def test_x_and_grok_combined_limit_and_restart_zero(tmp_path):
    b, llm = mk(tmp_path, limit=1.0, cost=0.3)
    b.state.add_spend(0.5)  # X portion
    b._draft("x", manual=True)  # 0.8 total: allowed
    assert b.state.api_run_spend() == pytest.approx(0.8) and not b.limit_exit
    b._charge(0.25, True)  # X pushes the combined total over the limit
    assert b.limit_exit and "API spend limit $1.00" in b.limit_exit
    n = len(llm.calls); b._draft("y", manual=True); assert len(llm.calls) == n  # no Grok request
    from xbot.xapi import XError
    with pytest.raises(XError):
        b._real()  # and no X request
    b2, _ = mk(tmp_path)
    assert b2.state.x_run_spend == 0.0 and b2.state.grok_run_spend == 0.0


class _SlowLLM:
    def __init__(self): self.calls = 0; self.last_cost_usd = 0.0
    def complete(self, s, u):
        self.calls += 1; import time; time.sleep(5); return "slow"


def test_reject_is_instant_and_hides_source(tmp_path):
    import time
    from xbot.bot import Bot
    from xbot.log import ActionLog
    from xbot.xapi import DryRunX
    c = Config(); c.max_pending = 2
    search = [{"id": str(i), "text": f"post {i} about rust", "author_id": f"a{i}", "username": f"u{i}",
               "public_metrics": {"like_count": 50}} for i in range(1, 8)]
    b = Bot(c, FakeLLM(), DryRunX([], search), ActionLog(sink=lambda *a: None), state_dir=tmp_path, save_config=lambda: None)
    b.tick()
    pend = [d for d in b.queue.pending() if d.source != "mention"]
    assert len(pend) == 2
    slow = _SlowLLM(); b.llm = slow
    class Hang(DryRunX):
        def __getattribute__(self, k):
            if k in ("search_recent", "mentions", "post", "get_post", "user_id"):
                time.sleep(5)
            return object.__getattribute__(self, k)
    b.dry_x = Hang([], []); b.real_x = Hang([], [])
    d = pend[0]
    t = time.monotonic(); b.handle(parse("/reject 1")); dt = time.monotonic() - t
    assert dt < 0.5 and slow.calls == 0
    assert b.queue.get(d.id).status == "rejected"
    src = next(p for p in b.found if str(p["id"]) == str(d.in_reply_to))
    assert src["user_hidden"] is True and any(p is src for _, p, _ in b.hidden_list())
    assert b.hidden(src)


def test_positions_per_section(tmp_path):
    b, _ = mk(tmp_path)
    q = b.queue
    s1 = q.add("reply", "a", "1", source="search"); m1 = q.add("reply", "b", "2", source="mention")
    s2 = q.add("reply", "c", "3", source="search")
    assert b.resolve_draft("1") == s1.id and b.resolve_draft("2") == s2.id and b.resolve_draft("m1") == m1.id
    assert b.resolve_draft("@%d" % s2.id) == s2.id and b.draft_label(s2.id) == "suggested 2"
    b.handle(parse("/reject 1"))
    assert b.resolve_draft("1") == s2.id  # renumbered
    with pytest.raises(KeyError):
        b.resolve_draft("m2")
    b.handle(parse("/edit m1 new text")); assert q.get(m1.id).text == "new text"


def test_balance_403_is_quiet_estimate_note():
    import urllib.error
    from xbot import credits as K
    def deny(url, key):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
    env = {"XAI_MANAGEMENT_KEY": "mk-SECRET", "XAI_TEAM_ID": "t1"}
    usd, err = K.fetch_balance(env, deny)
    assert usd is None and isinstance(err, K.BalanceDenied) and err.code == 403 and err.step == "balance"
    assert "management key lacks billing access" in err and "SECRET" not in err
    env2 = {"XAI_MANAGEMENT_KEY": "mk", "XAI_API_KEY": "ak"}
    assert K.fetch_balance(env2, deny)[1].step == "team lookup"
    def boom(url, key):
        raise urllib.error.HTTPError(url, 500, "x", {}, None)
    assert not isinstance(K.fetch_balance(env, boom)[1], K.BalanceDenied)


def test_credits_refresh_403_info_once_no_retry(monkeypatch):
    from types import SimpleNamespace
    from xbot import credits as K
    from xbot.app import XBotApp
    calls, logs = [], []
    def fb():
        calls.append(1); return None, K.BalanceDenied(403)
    monkeypatch.setattr(K, "fetch_balance", fb)
    bot = SimpleNamespace(log=SimpleNamespace(event=lambda k, m, **d: logs.append((k, m))))
    fake = SimpleNamespace(bot=bot, run_worker=lambda f, **k: f(), call_from_thread=lambda f: None, refresh_ui=None)
    XBotApp._credits_refresh(fake); XBotApp._credits_refresh(fake)
    assert calls == [1] and [k for k, _ in logs] == ["info"]
    assert "showing estimate" in bot.credit_note
