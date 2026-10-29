import base64, importlib.util, os, stat, tarfile
from pathlib import Path
from urllib.parse import quote
import pytest
from xbot import secure
from xbot.state import BotState
from xbot.queue import DraftQueue

FAKE = {"XAI_API_KEY": "xai-FAKEfakeFAKE1234567890abcd", "X_API_KEY": "FAKEconsumerKEY9876543210",
        "X_API_SECRET": "FAKEconsumerSECRET/+=abc123", "X_ACCESS_TOKEN": "111-FAKEaccessTOKENzzz",
        "X_ACCESS_TOKEN_SECRET": "FAKEaccessSECRETqqq777"}


def forms(v):
    return {v, quote(v, safe=""), base64.b64encode(v.encode()).decode().rstrip("=")}


def test_secret_wrapper_hides_value():
    s = secure.Secret("supersecretvalue123")
    assert repr(s) == "'***'" and str(s) == "***" and f"{s}" == "***" and s.reveal() == "supersecretvalue123"


def test_redact_all_forms(monkeypatch):
    for k, v in FAKE.items():
        monkeypatch.setenv(k, v)
    v = FAKE["X_API_SECRET"]
    for f in forms(v) | {f"Bearer {FAKE['XAI_API_KEY']}", "Basic " + base64.b64encode(f"{FAKE['X_API_KEY']}:{v}".encode()).decode()}:
        out = secure.redact(f"x {f} y")
        assert all(g not in out for g in forms(v) | forms(FAKE["XAI_API_KEY"])), out
    assert secure.redact("Authorization: Bearer abcdefghijklmnop") == "Authorization: Bearer ***"


def test_fake_secrets_never_reach_output_files(mk, monkeypatch, tmp_path, capsys):
    import xbot.config as C, xbot.app as A, logging
    for k, v in FAKE.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(C, "STATE_DIR", tmp_path)
    secure.install()
    b = mk(search=[], **{"post_every_n_ticks": 0})
    b.log.dir = tmp_path; b.log.path = tmp_path / "actions.jsonl"
    leak = " ".join(f"{v} {quote(v, safe='')} Bearer {v}" for v in FAKE.values())
    b.log.event("error", f"request failed {leak}", detail=leak)
    st = BotState(tmp_path / "state.json"); st.save()
    q = DraftQueue(tmp_path / "queue.json"); q.add("post", "hello")
    logging.getLogger("urllib3").warning("header %s", FAKE["XAI_API_KEY"])
    try:
        raise RuntimeError(f"boom with {leak}")
    except RuntimeError as e:
        line = A._crash_log(e)
    out = capsys.readouterr()
    blobs = [line, out.out, out.err] + [p.read_text() for p in tmp_path.iterdir() if p.is_file()]
    assert (tmp_path / "crash.log").exists() and (tmp_path / "actions.jsonl").exists()
    for v in FAKE.values():
        for f in forms(v):
            assert not any(f in t for t in blobs), "leaked a form of a fake secret"
    for p in tmp_path.iterdir():
        if p.is_file():
            assert stat.S_IMODE(p.stat().st_mode) == 0o600, p


def test_safe_env_has_no_secrets(monkeypatch):
    for k, v in FAKE.items():
        monkeypatch.setenv(k, v)
    env = secure.safe_env()
    assert "PATH" in env and not set(FAKE) & set(env) and not any(v in env.values() for v in FAKE.values())


def test_opener_and_mpv_get_minimal_env(monkeypatch):
    from xbot import opener, video
    from xbot.config import Config
    monkeypatch.setenv("XAI_API_KEY", FAKE["XAI_API_KEY"])
    got = []
    opener.open_url("https://x.com/a", which=lambda n: "/bin/x", popen=lambda c, **k: got.append(k), wsl=False)
    assert "XAI_API_KEY" not in got[0]["env"]
    calls = []
    video.run_mpv("https://v/x.mp4", Config(), run=lambda a, **k: calls.append(k), which=lambda n: "/usr/bin/mpv",
                  size=(80, 24), tty=None)
    assert all("XAI_API_KEY" not in k["env"] for k in calls)


@pytest.mark.parametrize("mode,why", [(0o640, "readable by others")])
def test_env_file_refused_when_open(tmp_path, mode, why):
    p = tmp_path / "env"; p.write_text("X=1"); os.chmod(p, mode)
    msg = secure.env_file_problem(p)
    assert why in msg and f"chmod 600 {p}" in msg and "--insecure-perms" in msg
    os.chmod(p, 0o600)
    assert secure.env_file_problem(p) is None


def test_env_file_symlink_refused(tmp_path):
    real = tmp_path / "real"; real.write_text("X=1"); os.chmod(real, 0o600)
    (tmp_path / "env").symlink_to(real)
    assert "symlink" in secure.env_file_problem(tmp_path / "env")


def test_main_refuses_open_env(tmp_path, monkeypatch, capsys):
    import xbot.config as C, xbot.app as A
    monkeypatch.setattr(C, "CONFIG_DIR", tmp_path / "cfg"); monkeypatch.setattr(C, "STATE_DIR", tmp_path / "st")
    monkeypatch.setattr(A, "STATE_DIR", tmp_path / "st", raising=False)
    (tmp_path / "cfg").mkdir(); e = tmp_path / "cfg" / "env"; e.write_text("X=1")
    monkeypatch.setattr(secure, "tighten", lambda dirs: [])  # don't auto-fix, to see the refusal
    os.chmod(e, 0o644)
    with pytest.raises(SystemExit) as ex:
        A.main(["search", "q"])
    assert ex.value.code == 2 and "chmod 600" in capsys.readouterr().err


def test_tighten_dirs_and_files(tmp_path):
    d = tmp_path / "s"; d.mkdir(); os.chmod(d, 0o755)
    f = d / "state.json"; f.write_text("{}"); os.chmod(f, 0o644)
    ch = secure.tighten([d])
    assert stat.S_IMODE(d.stat().st_mode) == 0o700 and stat.S_IMODE(f.stat().st_mode) == 0o600 and len(ch) == 2


def test_secret_cmd_hook(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    class R: returncode = 0; stdout = "XAI_API_KEY=xai-fromCMDvalue123456\n# c\n"
    n = secure.load_secret_cmd("pass show xbot", run=lambda *a, **k: R())
    assert n == 1 and os.environ["XAI_API_KEY"] == "xai-fromCMDvalue123456" and "fromCMD" not in secure.redact("k=xai-fromCMDvalue123456")


def test_tarball_check(tmp_path):
    spec = importlib.util.spec_from_file_location("ct", Path(__file__).parent.parent / "scripts/check_tarball.py")
    ct = importlib.util.module_from_spec(spec); spec.loader.exec_module(ct)
    good, bad = tmp_path / "g.tgz", tmp_path / "b.tgz"
    (tmp_path / "a.py").write_text("x"); (tmp_path / "env").write_text("X=1"); (tmp_path / "actions.jsonl").write_text("")
    (tmp_path / ".env.example").write_text("")
    with tarfile.open(good, "w:gz") as t:
        t.add(tmp_path / "a.py", "xbot/a.py"); t.add(tmp_path / ".env.example", "xbot/.env.example")
    with tarfile.open(bad, "w:gz") as t:
        t.add(tmp_path / "env", "xbot/env"); t.add(tmp_path / "actions.jsonl", "xbot/actions.jsonl")
    assert ct.bad_members(good) == [] and len(ct.bad_members(bad)) == 2
