"""Config, paths, env loading. Never log secret values."""
import json, os
from dataclasses import dataclass, asdict, field
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XBOT_CONFIG_DIR", Path.home() / ".config/xbot"))
STATE_DIR = Path(os.environ.get("XBOT_STATE_DIR", Path.home() / ".local/state/xbot"))
X_KEYS = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")
HAND_EDIT_WARNING = "Editing this file by hand can break xbot; use `xbot config <key> <value>` instead."
NONEMPTY = ("search_query", "model", "base_url")
SECRET_KEYS = ("XAI_API_KEY", "X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET", "X_BEARER_TOKEN", "XAI_MANAGEMENT_KEY")


@dataclass
class Config:
    model: str = "grok-4.7"
    base_url: str = "http://127.0.0.1:8767/v1"
    persona: str = "You are a thoughtful, concise, friendly account. No hashtags spam, no emojis overload."
    topics: list = field(default_factory=lambda: ["AI", "Linux", "building in public"])
    post_every_n_ticks: int = 15
    dry_run: bool = True
    max_chars: int = 280
    search_enabled: bool = True
    search_backfill: bool = True  # one extra older-posts call when a search yields few new posts
    search_query: str = ('(AI OR LLM OR programming OR Linux OR "open source" OR opensource OR devops OR rust OR python) '
                         '-is:retweet -is:reply -is:quote lang:en min_likes:20')
    search_max_results: int = 10
    search_every_n_ticks: int = 5
    max_replies_per_hour: int = 6
    allow_skip: bool = True
    daily_cap_usd: float = 0.0  # 0 = no cap
    max_pending: int = 4  # suggested-reply drafts shown at once (/maxpending n)
    max_mention_drafts: int = 4  # pending mention-reply drafts; extra mentions wait undrafted (0 = unlimited, /maxmentions n)
    queue_size_migrated: bool = False  # old configs saved the former default 10; moved to 4 once
    excluded_tags: list = field(default_factory=list)
    auto_filter: bool = True  # master switch for /filter
    filter_topics: list = field(default_factory=lambda: ["adult", "spam", "x-flags"])
    x_flags_migrated: bool = False
    filter_words: list = field(default_factory=list)
    topic_edits: dict = field(default_factory=dict)  # topic -> {'add': [...], 'remove': [...]}
    blocked_authors: list = field(default_factory=list)  # lowercase handles, no @
    filtered_mentioners: list = field(default_factory=list)  # handles whose mentions are hidden (q in queue)
    muted_authors: dict = field(default_factory=dict)  # handle -> {'id', 'live': bool}
    taxonomy: object = None  # None = built-in DEFAULT_TAXONOMY; or {tag: [keywords]}
    search_query_limit: int = 512  # X recent search query length (self-serve 512)
    oembed_prefetch: bool = True  # free author name/@handle lookup for new posts
    # removed keys (preview_renderer, video_player) in old config files are ignored on load
    video_vo: str = "auto"  # mpv output: auto (sixel if detected, else tct) | sixel | tct
    video_audio: str = "off"  # off = mpv runs muted
    video_scale: float = 0.6  # share of the picture area for videos/GIFs in the sixel viewer (0.2-1.0); photos use all of it
    sixel_scale: str = "auto"  # auto = measure the terminal (CSI 14t/16t + TIOCGWINSZ); or a factor (e.g. 1.25) if the viewer box is too small/big
    draft_batch: int = 8  # max search posts per Grok request (fills free slots, rest prefilled); 1 = one post per request
    style_examples: int = 8  # few-shot examples from your edited drafts in the prompt; 0 disables
    prefill_max: int = 20  # stored drafts for upcoming feed posts; full + queue full = no Grok requests
    llm_rpm: int = 5  # max Grok requests per minute in total (match the key's limit; 0 = no pacing)
    llm_auto_rpm: int = 4  # of those, max per minute for AUTO drafting; the rest is reserved for manual g drafts
    spend_limit: float = 5.0  # per-run xAI (Grok) spend limit in USD, always on (<= 0 in the file = $5); reached = save, reset counter, exit
    credits_start: float = 0.0  # xAI credits (USD) you had on credits_start_date, for "est. credits left" (0 = off)
    credits_start_date: str = ""  # YYYY-MM-DD (UTC); empty = count all tracked Grok spend
    reads_live: object = None  # None=auto (live if X keys present), True, False

    @classmethod
    def load(cls, config_dir: Path = None):
        p = Path(config_dir or CONFIG_DIR) / "config.json"
        c = cls()
        c.load_error = None
        c.load_warnings = []
        if p.exists():
            try:
                data = json.loads(p.read_text())
                if not isinstance(data, dict):
                    raise ValueError("top level must be a JSON object {...}")
            except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
                where = f" line {e.lineno} col {e.colno}" if isinstance(e, json.JSONDecodeError) else ""
                msg = e.msg if isinstance(e, json.JSONDecodeError) else str(e)
                c.load_error = f"xbot: config error in {p}{where}: {msg} (fix it with xbot config edit, or xbot config reset; using defaults)"
                data = {}
            c.load_warnings = []
            d0 = cls()
            for k, v in data.items():
                if not hasattr(d0, k) or k.startswith("_"):
                    continue
                dv = getattr(d0, k)
                bad = (k in NONEMPTY and not (isinstance(v, str) and v.strip())) or (
                    dv is not None and v is not None and not isinstance(v, type(dv))
                    and not (isinstance(dv, float) and isinstance(v, int) and not isinstance(v, bool))) or (
                    isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0)
                if bad:
                    c.load_warnings.append(f"xbot: config error in {p}: bad {k} value, using default (xbot config {k} <value>)")
                    continue
                setattr(c, k, v)
            if c.llm_rpm and c.llm_auto_rpm > c.llm_rpm:
                c.llm_auto_rpm = c.llm_rpm
            if not data.get("queue_size_migrated"):
                for k in ("max_pending", "max_mention_drafts"):
                    if data.get(k) == 10:  # the old default, not a user choice
                        setattr(c, k, 4)
                c.queue_size_migrated = True
            if "untagged" in (c.excluded_tags or []):  # removed pseudo-tag
                c.excluded_tags = [t for t in c.excluded_tags if t != "untagged"]
        c.base_url = os.environ.get("XBOT_BASE_URL", c.base_url)
        c.model = os.environ.get("XBOT_MODEL", c.model)
        return c

    def save(self, config_dir: Path = None):
        d = Path(config_dir or CONFIG_DIR)
        d.mkdir(parents=True, exist_ok=True)
        p = d / "config.json"
        if getattr(self, "load_error", None) and p.exists():
            bad = d / "config.json.bad"  # keep the hand-edited file instead of overwriting it silently
            if not bad.exists():
                p.replace(bad)
            self.load_error = None
        from .secure import write_private
        write_private(p, json.dumps({k: v for k, v in asdict(self).items()}, indent=2))  # atomic, 0600


def load_env_file(config_dir: Path = None):
    """Load KEY=VALUE from ~/.config/xbot/env into os.environ (env vars win). Warn if perms too open."""
    p = Path(config_dir or CONFIG_DIR) / "env"
    warnings = []
    if not p.exists():
        return warnings
    if p.stat().st_mode & 0o077:
        warnings.append(f"{p} is readable by others; run: chmod 600 {p}")
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        from .secure import register
        register(v) if k.strip() in SECRET_KEYS or any(h in k.lower() for h in ("key", "secret", "token", "pass")) else None
        os.environ.setdefault(k.strip(), v)
    return warnings


def redact(text: str) -> str:
    """Hide every loaded secret (raw, base64, percent-encoded, Bearer/Basic)."""
    from .secure import redact as _r
    return _r(text)


def x_keys_present():
    return all(os.environ.get(k) for k in X_KEYS)
