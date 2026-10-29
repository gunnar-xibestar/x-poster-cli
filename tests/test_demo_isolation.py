import os
import xbot.sample as S
from xbot import config as C, log as L


def _snap(root):
    return {str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*")}


async def test_demo_changes_never_touch_real_config_or_state(tmp_path, monkeypatch):
    home = tmp_path / "home"
    real_cfg, real_state = home / ".config/xbot", home / ".local/state/xbot"
    real_cfg.mkdir(parents=True); real_state.mkdir(parents=True)
    (real_cfg / "config.json").write_text('{"spend_limit": 7}')
    (real_cfg / "env").write_text("XAI_MANAGEMENT_KEY=\n"); os.chmod(real_cfg / "env", 0o600)
    for k, v in {"HOME": home, "XDG_CONFIG_HOME": home / ".config", "XDG_STATE_HOME": home / ".local/state"}.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.delenv("XBOT_CONFIG_DIR", raising=False); monkeypatch.delenv("XBOT_STATE_DIR", raising=False)
    monkeypatch.setattr(C, "CONFIG_DIR", real_cfg); monkeypatch.setattr(C, "STATE_DIR", real_state)
    monkeypatch.setattr(L, "STATE_DIR", real_state)
    before = _snap(home)
    demo = tmp_path / "demo"  # outside the fake HOME
    app = S.demo_app(demo)
    async with app.run_test(size=(160, 45)) as pilot:
        await pilot.pause(); await pilot.pause()
        b = app.bot
        assert C.CONFIG_DIR != real_cfg and C.STATE_DIR != real_state
        for cmd in ("/limit 3", "/cap 1.5", "/maxresults 20", "/maxpending 3", "/align be terse", "/model grok-x",
                    "/search rust", "/exclude crypto", "/filter hide kubernetes", "/filter off", "/block @devjane",
                    "/mute @opsdan", "/edit 1 changed text", "/reject 2", "/reads off", "/backfill on", "/export"):
            app._run(cmd); await pilot.pause()
        b.hide_post(1, forever=True)
        b.state.add_spend(0.25)
        b.log.event("info", "demo action")
        from xbot.app import _crash_log
        _crash_log(RuntimeError("demo crash"))
        app.query_one("#cmd").history.append("/limit 3")
        await pilot.press("ctrl+q"); await pilot.pause()
    assert _snap(home) == before  # nothing created/modified under the real HOME
    assert C.CONFIG_DIR == real_cfg and C.STATE_DIR == real_state and L.STATE_DIR == real_state  # restored
    assert "XBOT_STATE_DIR" not in os.environ
    assert any(demo.rglob("crash.log"))  # it went to the demo dir instead
