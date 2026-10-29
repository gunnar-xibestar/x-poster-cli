import subprocess, sys
import pytest
from xbot import app


def test_help_prints_usage_and_exits_0_without_tui(capsys, monkeypatch):
    monkeypatch.setattr(app, "XBotApp", lambda *a, **k: pytest.fail("TUI launched"))
    monkeypatch.setattr(app, "probe_graphics", lambda *a, **k: pytest.fail("graphics probe"))
    import xbot.secure as sec
    monkeypatch.setattr(sec, "install", lambda *a, **k: pytest.fail("touched secrets/state"))
    for arg in ("--help", "-h", "help"):
        with pytest.raises(SystemExit) as e:
            app.main([arg])
        assert e.value.code == 0 and "usage: xbot" in capsys.readouterr().out


def test_unknown_argument_exits_2(capsys, monkeypatch):
    monkeypatch.setattr(app, "XBotApp", lambda *a, **k: pytest.fail("TUI launched"))
    with pytest.raises(SystemExit) as e:
        app.main(["--bogus"])
    assert e.value.code == 2 and "unknown argument" in capsys.readouterr().err


def test_python_m_xbot_help_subprocess(tmp_path):
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-m", "xbot", "--help"], capture_output=True, text=True, timeout=20, env=env)
    assert r.returncode == 0 and "usage: xbot" in r.stdout
    assert not (tmp_path / ".local").exists() and not (tmp_path / ".config").exists()
