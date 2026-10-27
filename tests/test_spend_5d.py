"""Rolling 5-day X + Grok spend: persisted per-charge records, survives session resets, shown and printed."""
import json
from xbot.state import BotState
from xbot import credits as K
from tests.test_spend_limit import mk

DAY = 86400


def test_window_cutoff_rolling_5x24h(tmp_path):
    t = [10 * DAY]
    st = BotState(tmp_path / "state.json", clock=lambda: t[0])
    st.add_grok_spend(1.00)                          # t0
    t[0] += 2 * DAY; st.add_spend(0.50)              # t0 + 2d (X)
    t[0] += 2 * DAY + 23 * 3600; st.add_grok_spend(0.25)  # t0 + 4d23h
    assert st.spent_5d() == 1.75
    t[0] = 10 * DAY + 5 * DAY - 1                    # 1 s before the first charge is 5 x 24h old
    assert st.spent_5d() == 1.75
    t[0] = 10 * DAY + 5 * DAY + 1                    # just past: dropped
    assert st.spent_5d() == 0.75
    st.add_spend(0.0)                                # charging prunes old records from the file
    assert len(json.loads((tmp_path / "state.json").read_text())["spend_log"]) == 2


def test_persists_across_restart_and_session_reset(tmp_path):
    t = [100 * DAY]
    st = BotState(tmp_path / "state.json", clock=lambda: t[0])
    st.add_grok_spend(0.40); st.add_spend(0.10)
    st.reset_run_spend()                             # what every exit does
    assert st.api_run_spend() == 0 and st.spent_5d() == 0.50
    again = BotState(tmp_path / "state.json", clock=lambda: t[0])  # next start
    again.reset_run_spend()
    assert again.spent_5d() == 0.50 and again.api_run_spend() == 0


def test_status_limit_and_exit_lines(tmp_path):
    t = [1000.0]
    b, _ = mk(tmp_path, limit=5, cost=0.42); b.session_start = t[0]; b.state.clock = lambda: t[0]
    b.state.spend_log = [[t[0] - 2 * DAY, 3.0], [t[0] - 6 * DAY, 9.0]]  # earlier sessions; one outside the window
    b._draft("x", manual=True)
    assert K.spend_lines(b)[0].endswith("[/] · 5d $3.42")
    assert "last 5 days $3.42 (X + Grok, not part of the limit)" in K.limit_summary(b.cfg, b.state)
    assert not K.limit_reached(b.cfg, b.state)  # 5-day total doesn't count toward the session limit
    t[0] += 60
    line = b.end_session()
    assert line.endswith("· API spent $0.42 of $5.00 limit (X $0.00 + Grok $0.42) · last 5 days $3.42")
    assert b.state.api_run_spend() == 0 and b.state.spent_5d() == 3.42  # session reset, 5d kept
