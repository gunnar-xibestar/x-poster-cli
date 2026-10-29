import socket
import xbot.sample as S
import xbot.credits as CR

KEYS = ("XAI_MANAGEMENT_KEY", "XAI_TEAM_ID", "XAI_API_KEY", "X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET", "X_BEARER_TOKEN", "X_CLIENT_ID", "X_CLIENT_SECRET", "X_REFRESH_TOKEN")


async def test_demo_makes_no_real_balance_or_network_call(tmp_path, monkeypatch):
    for k in KEYS:
        monkeypatch.setenv(k, "fake-not-a-real-key")
    calls = []
    real_fetch = CR.fetch_balance
    monkeypatch.setattr(CR, "fetch_balance", lambda *a, **k: (calls.append("balance"), real_fetch(*a, **k))[1])

    def no_net(*a, **k):
        calls.append(("connect", a)); raise OSError("network disabled in demo test")
    monkeypatch.setattr(socket.socket, "connect", no_net)
    monkeypatch.setattr(socket, "create_connection", no_net)
    restore = None
    try:
        app = S.demo_app(tmp_path / "demo"); restore = app._restore_sandbox
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause(); await pilot.pause()
            app._run("/tick"); await app.workers.wait_for_complete(); await pilot.pause()
            await pilot.press("ctrl+q"); await pilot.pause()
    finally:
        if restore: restore()
    assert calls == []
    import os
    assert not any(os.environ.get(k) for k in KEYS)
