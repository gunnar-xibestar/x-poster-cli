"""`xbot config`: show or change ~/.config/xbot/config.json from the shell."""
import json, os, subprocess
from dataclasses import fields
from pathlib import Path
from . import config as C

SECRET_HINTS = ("key", "secret", "token", "password")
SKIP = {"queue_size_migrated", "x_flags_migrated", "draft_batch_migrated"}  # internal bookkeeping


def _redact(k, v):
    if any(h in k.lower() for h in SECRET_HINTS) and isinstance(v, str) and v:
        return "***"
    return C.redact(v) if isinstance(v, str) else v


def _parse(cur, raw):
    """Parse raw by the current value's type. Raises ValueError with a friendly message."""
    if isinstance(cur, bool) or cur is None and raw.lower() in ("true", "false", "auto", "none"):
        r = raw.lower()
        if r in ("true", "on", "yes", "1"): return True
        if r in ("false", "off", "no", "0"): return False
        if cur is None and r in ("auto", "none"): return None
        raise ValueError(f"expected true/false, got {raw!r}")
    if isinstance(cur, int):
        try: return int(raw)
        except ValueError: raise ValueError(f"expected a whole number, got {raw!r}") from None
    if isinstance(cur, float):
        try: return float(raw)
        except ValueError: raise ValueError(f"expected a number, got {raw!r}") from None
    if isinstance(cur, (list, dict)):
        try: v = json.loads(raw)
        except json.JSONDecodeError:
            if isinstance(cur, list): return [s.strip() for s in raw.split(",") if s.strip()]
            raise ValueError("expected JSON, e.g. {}") from None
        if not isinstance(v, type(cur)): raise ValueError(f"expected a JSON {type(cur).__name__}")
        return v
    return raw


def validate(c):
    """Range checks + clamps. Returns notes about adjustments."""
    notes = []
    from .video import VOS, AUDIO
    for k, ok in (("video_vo", VOS), ("video_audio", AUDIO)):
        if getattr(c, k, ok[0]) not in ok:
            raise ValueError(f"{k} must be one of {', '.join(ok)}")
    from .video import SCALE_BOUNDS
    try:
        vs = float(getattr(c, "video_scale", 0.6))
    except (TypeError, ValueError):
        raise ValueError("video_scale must be a number between 0.2 and 1.0") from None
    if not (SCALE_BOUNDS[0] <= vs <= SCALE_BOUNDS[1]):
        raise ValueError(f"video_scale must be between {SCALE_BOUNDS[0]} and {SCALE_BOUNDS[1]}")
    c.video_scale = vs
    ss = str(getattr(c, "sixel_scale", "auto") or "auto").strip().lower()
    if ss != "auto":
        try:
            f = float(ss)
        except ValueError:
            raise ValueError("sixel_scale must be auto or a number between 0.5 and 3.0") from None
        if not (0.5 <= f <= 3.0):
            raise ValueError("sixel_scale must be auto or a number between 0.5 and 3.0")
        ss = str(f)
    c.sixel_scale = ss
    if c.llm_rpm < 0:
        raise ValueError("llm_rpm must be >= 1, or 0 to turn pacing off")
    if c.llm_auto_rpm < 0:
        raise ValueError("llm_auto_rpm must be >= 0")
    if c.llm_rpm and c.llm_auto_rpm > c.llm_rpm:
        c.llm_auto_rpm = c.llm_rpm; notes.append(f"llm_auto_rpm clamped to llm_rpm ({c.llm_rpm})")
    for k in ("max_pending", "max_mention_drafts", "max_replies_per_hour", "max_chars", "search_max_results"):
        if getattr(c, k) < 0: raise ValueError(f"{k} must be >= 0")
    d = getattr(c, "credits_start_date", "")
    if d:
        import time
        try: time.strptime(d, "%Y-%m-%d")
        except ValueError: raise ValueError("credits_start_date must be YYYY-MM-DD (or empty)") from None
    return notes


def cli(argv, config_dir=None, out=print, run=subprocess.call, ask=input):
    d = Path(config_dir or C.CONFIG_DIR); path = d / "config.json"
    c = C.Config.load(d)
    keys = [f.name for f in fields(c) if f.name not in SKIP]
    if not argv or argv[0] not in ("edit", "reset"):
        for w in ([c.load_error] if c.load_error else []) + c.load_warnings:
            out("warning: " + w)
    if not argv:
        out(f"# {path}" + ("" if path.exists() else " (not created yet: defaults)"))
        for k in keys:
            out(f"{k} = {json.dumps(_redact(k, getattr(c, k)))}")
        out("# set: xbot config <key> <value>   edit: xbot config edit")
        return 0
    if argv[0] == "reset":
        import time
        bak = None
        if path.exists():
            bak = d / f"config.json.bak.{time.strftime('%Y%m%d-%H%M%S')}"
            path.replace(bak)
        fresh = C.Config(); fresh.load_error = None; fresh.save(d)
        out(f"config reset to defaults; old file backed up to {bak}" if bak else f"config reset to defaults ({path})")
        return 0
    if argv[0] == "edit":
        if not path.exists(): c.save(d)
        out(C.HAND_EDIT_WARNING)
        while True:
            rc = run([*(os.environ.get("EDITOR") or "nano").split(), str(path)])
            n = C.Config.load(d)
            probs = ([n.load_error] if n.load_error else []) + n.load_warnings
            if not probs:
                out("config OK"); return rc
            for w in probs: out(w)
            try:
                again = ask("Reopen editor? [Y/n] ").strip().lower()
            except EOFError:
                again = "n"
            if again not in ("", "y", "yes"):
                return 2
    k = argv[0]
    if k not in keys:
        out(f"unknown setting {k!r}. Valid keys: {', '.join(keys)}"); return 2
    if len(argv) == 1:
        out(f"{k} = {json.dumps(_redact(k, getattr(c, k)))}"); return 0
    try:
        if k in ("spend_limit", "credits_start"):
            from .credits import parse_usd, parse_limit
            setattr(c, k, (parse_limit if k == "spend_limit" else parse_usd)(" ".join(argv[1:])))
        else:
            setattr(c, k, _parse(getattr(c, k), " ".join(argv[1:])))
        notes = validate(c)
    except ValueError as e:
        out(f"{k}: {e}"); return 2
    if c.load_error:
        out(f"note: the broken file is kept as {d / 'config.json.bad'}; other settings are back to defaults")
    c.save(d)
    for n in notes: out(n)
    out(f"{k} = {json.dumps(_redact(k, getattr(c, k)))}  (saved to {path}; restart xbot to apply)")
    return 0
