"""`xbot secrets`: edit ~/.config/xbot/env in nano (CLI only). Never prints or logs values."""
import os, re, shutil, subprocess
from pathlib import Path

TEMPLATE = """XAI_MANAGEMENT_KEY=
# xbot secrets: KEY=value, one per line. Lines starting with # are ignored. Never share this file.
# xAI (Grok drafting):
# XAI_API_KEY=
# XAI_MANAGEMENT_KEY (top line): real credit balance; key from console.x.ai settings, optional, blank = off
# XAI_TEAM_ID=
# X API (OAuth 1.0a user context):
# X_API_KEY=
# X_API_SECRET=
# X_ACCESS_TOKEN=
# X_ACCESS_TOKEN_SECRET=
# X_BEARER_TOKEN=
# X OAuth 2.0 (xbot login):
# X_CLIENT_ID=
# X_CLIENT_SECRET=
# Non-secret settings:
# XBOT_BASE_URL=https://api.x.ai/v1
# XBOT_MODEL=grok-4.7
"""
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# -I: ignore nanorc (so no rc can turn on backups, locking or history); no -B backups; -R restricted mode:
# no reading/writing other files (and no backups); no --locking, so no .swp lock file.
NANO_FLAGS = ["-I", "-R"]


def ensure_file(p):
    old = os.umask(0o077)
    try:
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(p.parent, 0o700)
        if not p.exists():
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try: os.write(fd, TEMPLATE.encode())
            finally: os.close(fd)
        os.chmod(p, 0o600)
    finally:
        os.umask(old)


def scan(text):
    """(names set to a non-empty value, line numbers that don't parse). Values are never returned."""
    names, bad = [], []
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[7:].strip()
        k, eq, v = s.partition("=")
        if not eq or not NAME_RE.match(k.strip()):
            bad.append(i); continue
        if v.strip().strip('"').strip("'"):
            names.append(k.strip())
    return names, bad


def editor_cmd(path, which=shutil.which, env=os.environ):
    if which("nano"):
        return [which("nano"), *NANO_FLAGS, str(path)]
    ed = env.get("EDITOR", "").split()
    if ed and which(ed[0]):
        return [*ed, str(path)]
    return None


def cli(argv=(), config_dir=None, out=print, run=subprocess.call, which=shutil.which):
    from . import config as C
    from .secure import safe_env
    p = Path(config_dir or C.CONFIG_DIR) / "env"
    ensure_file(p)
    cmd = editor_cmd(p, which)
    if cmd is None:
        out(f"no editor found (install nano). Edit this file yourself, mode 600: {p}")
        return 1
    env = safe_env({"EDITOR": os.environ.get("EDITOR", "")} if "nano" not in cmd[0] else None)
    old = os.umask(0o077)
    try:
        rc = run(cmd, env=env)
    finally:
        os.umask(old)
    os.chmod(p, 0o600)
    names, bad = scan(p.read_text())
    out(f"{p} (mode 600)")
    out("set: " + (", ".join(names) if names else "(none)"))
    if bad:
        out("lines that don't parse as KEY=value (fix them): " + ", ".join(map(str, bad)))
    out("restart xbot to load the changes")
    return rc or 0
