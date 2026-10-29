"""Secrets hygiene: private file modes, env-file checks, redaction, minimal subprocess env."""
import base64, logging, os, re, shlex, stat, subprocess, sys, threading
from pathlib import Path
from urllib.parse import quote, quote_plus

_SECRETS: set = set()
AUTH_RE = re.compile(r"\b(Bearer|Basic|OAuth)\s+[A-Za-z0-9._~+/=%,\"-]{8,}", re.I)
ENV_ALLOW = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "TERM", "COLORTERM",
             "TERM_PROGRAM", "DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS",
             "PULSE_SERVER", "WSL_DISTRO_NAME", "WSL_INTEROP", "WSLENV", "WT_SESSION", "TMPDIR", "BROWSER", "SYSTEMROOT")


class Secret(str):
    """A str that never shows itself in repr/str/format; use .reveal() where the real value is needed."""
    def __new__(cls, v):
        o = super().__new__(cls, v); register(v); return o
    def reveal(self):
        return str.__str__(self)
    def __repr__(self):
        return "'***'"
    def __str__(self):
        return "***"
    def __format__(self, spec):
        return "***"


def register(value):
    v = str(value or "")
    if len(v) >= 6:
        _SECRETS.add(v)


def secret_names():
    from .config import SECRET_KEYS
    return tuple(SECRET_KEYS) + ("XBOT_SECRET",)


def register_env():
    for k in secret_names():
        if os.environ.get(k):
            register(os.environ[k])


def _forms(v):
    b = v.encode()
    out = {v, quote(v, safe=""), quote_plus(v), base64.b64encode(b).decode(), base64.urlsafe_b64encode(b).decode()}
    out |= {f.rstrip("=") for f in list(out) if f.endswith("=")}
    return {f for f in out if len(f) >= 6}


def redact(text):
    if not isinstance(text, str):
        text = str(text)
    register_env()
    vals = sorted(_SECRETS, key=len, reverse=True)
    for v in vals:
        for f in _forms(v):
            if f in text:
                text = text.replace(f, "***")
    if len(vals) >= 2:  # Basic auth of key:secret pairs
        for a in vals:
            for c in vals:
                if a != c:
                    t = base64.b64encode(f"{a}:{c}".encode()).decode()
                    if t in text:
                        text = text.replace(t, "***")
    return AUTH_RE.sub(lambda m: m.group(1) + " ***", text)


class RedactFilter(logging.Filter):
    def filter(self, record):
        try:
            record.msg = redact(record.getMessage()); record.args = ()
        except Exception:
            pass
        return True


def install():
    """umask 077, redacting log filter + excepthooks, quiet HTTP header debug logging."""
    os.umask(0o077)
    f = RedactFilter()
    root = logging.getLogger()
    root.addFilter(f)
    for h in root.handlers:
        h.addFilter(f)
    for name in ("urllib3", "requests", "requests_oauthlib", "oauthlib", "httpx", "httpcore", "openai"):
        lg = logging.getLogger(name); lg.setLevel(logging.WARNING); lg.addFilter(f)
    try:
        import http.client
        http.client.HTTPConnection.debuglevel = 0
    except Exception:
        pass
    prev = sys.excepthook
    def hook(t, e, tb):
        import traceback
        sys.stderr.write(redact("".join(traceback.format_exception(t, e, tb))))
    if getattr(prev, "__name__", "") != "hook":
        sys.excepthook = hook
    threading.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)


def safe_env(extra=None, source=None):
    """Minimal environment for child processes (mpv, browser openers): no secret variables."""
    src = os.environ if source is None else source
    env = {k: src[k] for k in ENV_ALLOW if k in src}
    env.update(extra or {})
    return env


def write_private(path, data, mode=0o600):
    """Atomic write: os.open(tmp, 0600) + fsync + os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # unique temp name per writer: a shared "x.tmp" let two threads (e.g. a worker + tick
    # both exporting found.json) race, and the loser's os.replace raised FileNotFoundError
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        try:
            os.write(fd, data.encode() if isinstance(data, str) else data); os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)  # never leave a stray .tmp behind (disk full, encode error, ...)
        except OSError:
            pass
        raise


def append_private(path, line):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line.encode())
    finally:
        os.close(fd)


def tighten(dirs):
    """Dirs 0700, their regular files 0600 (only ours, never through symlinks). Returns changed paths."""
    changed = []
    for d in dirs:
        d = Path(d)
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        st = os.lstat(d)
        if stat.S_ISLNK(st.st_mode) or st.st_uid != os.getuid():
            continue
        if st.st_mode & 0o077:
            os.chmod(d, 0o700); changed.append(str(d))
        for p in d.iterdir():
            s = os.lstat(p)
            if stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid() and s.st_mode & 0o077:
                os.chmod(p, 0o600); changed.append(str(p))
    return changed


def env_file_problem(p):
    """One-line refusal message (with the exact fix) if the env file is unsafe, else None."""
    p = Path(p)
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return None
    home_env = Path.home() / ".config/xbot/env"
    if stat.S_ISLNK(st.st_mode):
        return (f"xbot: refusing to start: {p} is a symlink (to {os.path.realpath(p)}); fix: "
                f"cp --remove-destination \"$(readlink -f {p})\" {p} && chmod 600 {p}  (or pass --insecure-perms)")
    if os.path.realpath(p).startswith("/mnt/"):
        return (f"xbot: refusing to start: {p} is on a Windows drive (/mnt/), where permissions don't protect it; "
                f"fix: mv {p} {home_env} && chmod 600 {home_env}  (or pass --insecure-perms)")
    if st.st_uid != os.getuid():
        return f"xbot: refusing to start: {p} is owned by uid {st.st_uid}, not you; fix: sudo chown $(id -u):$(id -g) {p} && chmod 600 {p}  (or pass --insecure-perms)"
    if st.st_mode & 0o077:
        return f"xbot: refusing to start: {p} is readable by others (mode {stat.S_IMODE(st.st_mode):o}); fix: chmod 600 {p}  (or pass --insecure-perms)"
    return None


def load_secret_cmd(cmd=None, run=subprocess.run):
    """XBOT_SECRET_CMD: a command whose stdout has KEY=VALUE lines (e.g. `pass show xbot`); env vars still win."""
    cmd = cmd if cmd is not None else os.environ.get("XBOT_SECRET_CMD")
    if not cmd:
        return 0
    r = run(shlex.split(cmd), capture_output=True, text=True, timeout=30, env=safe_env())
    if r.returncode != 0:
        raise RuntimeError(f"XBOT_SECRET_CMD failed (exit {r.returncode})")
    n = 0
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1); k, v = k.strip(), v.strip().strip('"').strip("'")
        register(v)
        if k not in os.environ:
            os.environ[k] = v; n += 1
    return n
