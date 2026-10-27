import os, stat
from xbot import envedit as S
from xbot.commands import parse, CommandError
import pytest


def which_nano(n):
    return "/usr/bin/nano" if n == "nano" else None


def test_creates_template_and_lists_names_only(tmp_path):
    d = tmp_path / "cfg"; out = []; seen = {}
    def run(cmd, env=None):
        seen["cmd"], seen["env"] = cmd, env
        p = cmd[-1]
        assert "XAI_MANAGEMENT_KEY" in open(p).read() and "=sk" not in open(p).read()
        open(p, "a").write("XAI_API_KEY=sekret-value-123\nexport X_API_KEY='abc'\nEMPTY=\ngarbage line\n")
        os.chmod(p, 0o644)
        return 0
    os.environ["XAI_API_KEY_LEAK_TEST"] = "x"
    assert S.cli([], config_dir=d, out=out.append, run=run, which=which_nano) == 0
    p = d / "env"
    assert stat.S_IMODE(p.stat().st_mode) == 0o600 and stat.S_IMODE(d.stat().st_mode) == 0o700
    assert seen["cmd"][:3] == ["/usr/bin/nano", "-I", "-R"] and "-B" not in seen["cmd"]
    assert "XAI_API_KEY_LEAK_TEST" not in seen["env"] and not any("KEY" in k for k in seen["env"])
    text = "\n".join(out)
    assert "XAI_API_KEY, X_API_KEY" in text and "EMPTY" not in text.split("set:")[1].split("\n")[0]
    assert "sekret" not in text and "abc" not in text
    assert "don't parse" in text and str(len(S.TEMPLATE.splitlines()) + 4) in text
    assert not list(d.glob("*~")) and not list(d.glob("*.swp"))


def test_existing_file_untouched_and_editor_fallback(tmp_path):
    p = tmp_path / "env"; p.write_text("X_API_KEY=v\n"); os.chmod(p, 0o640)
    cmds = []
    os.environ["EDITOR"] = "vi"
    w = lambda n: "/usr/bin/vi" if n == "vi" else None
    S.cli([], config_dir=tmp_path, out=lambda m: None, run=lambda c, env=None: cmds.append(c) or 0, which=w)
    assert cmds[0] == ["vi", str(p)] and p.read_text() == "X_API_KEY=v\n"
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_no_editor_prints_path(tmp_path):
    out = []
    assert S.cli([], config_dir=tmp_path, out=out.append, run=lambda *a, **k: 0, which=lambda n: None) == 1
    assert str(tmp_path / "env") in out[0] and (tmp_path / "env").exists()


def test_no_tui_secrets_command():
    with pytest.raises(CommandError):
        parse("/secrets")
