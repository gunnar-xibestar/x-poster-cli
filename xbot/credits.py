"""xAI (Grok) spend tracking, the per-run spend limit, and the API-credit balance line.

Prices: docs.x.ai/docs/models (checked 2026-10-26), USD per 1M tokens. xAI also returns the exact cost of each
request in usage.cost_in_usd_ticks (1 USD = 10_000_000_000 ticks); that is used whenever present.
Balance: GET https://management-api.x.ai/v1/billing/teams/{team_id}/prepaid/balance with a *management* key
(docs.x.ai/docs/management-api/billing). total.val is USD cents, negative = credit left.
"""
import json, os, time, urllib.request

# model -> (input, cached input, output) USD per 1M tokens
PRICES = {"grok-4.7": (2.00, 0.50, 6.00), "grok-4.6": (2.00, 0.50, 6.00), "grok-4.5": (2.00, 0.30, 6.00)}
TICKS_PER_USD = 10_000_000_000
MGMT_BASE = "https://management-api.x.ai"
API_BASE = "https://api.x.ai"
REFRESH_S = 300
DEFAULT_LIMIT = 5.0  # the per-run spend limit is always on; config values <= 0 fall back to this


def _g(o, k, d=None):
    return (o.get(k, d) if isinstance(o, dict) else getattr(o, k, d))


def cost_from_usage(model, usage):
    """USD for one response's usage (exact ticks if xAI sent them, else token count x docs price)."""
    if usage is None:
        return 0.0
    ticks = _g(usage, "cost_in_usd_ticks")
    if ticks:
        return int(ticks) / TICKS_PER_USD
    pin, pcached, pout = PRICES.get(model, PRICES["grok-4.7"])
    inp = _g(usage, "prompt_tokens") or _g(usage, "input_tokens") or 0
    out = _g(usage, "completion_tokens") or _g(usage, "output_tokens") or 0
    det = _g(usage, "prompt_tokens_details") or _g(usage, "input_tokens_details")
    cached = (_g(det, "cached_tokens") or 0) if det is not None else 0
    cdet = _g(usage, "completion_tokens_details")
    reasoning = (_g(cdet, "reasoning_tokens") or 0) if cdet is not None else 0
    return ((inp - cached) * pin + cached * pcached + (out + reasoning) * pout) / 1e6


def effective_limit(cfg):
    v = getattr(cfg, "spend_limit", DEFAULT_LIMIT)
    return v if isinstance(v, (int, float)) and v > 0 else DEFAULT_LIMIT


def limit_reached(cfg, state):
    return state.api_run_spend() >= effective_limit(cfg)


def limit_message(limit, spent):
    return (f"xbot stopped: API spend limit ${limit:.2f} reached (spent ${spent:.2f} this session, X + Grok). "
            f"The session spend counter was reset to $0 for the next start; the limit is unchanged "
            f"(raise it with: xbot config spend_limit <amount>).")


def fmt_duration(sec):
    sec = max(0, int(sec)); h, m = sec // 3600, sec % 3600 // 60
    return f"{h}h {m}m" if h else (f"{m}m" if m else f"{sec}s")


def breakdown(state):
    return f"X ${state.x_run_spend:.2f} + Grok ${state.grok_run_spend:.2f}"


def session_summary(duration_s, spent, limit, reason=None, parts="", last5=None):
    s = f"xbot session: {fmt_duration(duration_s)} · API spent ${spent:.2f} of ${limit:.2f} limit" + (f" ({parts})" if parts else "")
    if last5 is not None:
        s += f" · last 5 days ${last5:.2f}"
    return s + (f"\n{reason}" if reason else "")


def est_left(cfg, state):
    if cfg.credits_start <= 0:
        return None
    return cfg.credits_start - state.grok_spent(since=cfg.credits_start_date or None)


def _get(url, key, timeout=10):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def fetch_balance(env=os.environ, get=_get):
    """(usd_left, None) from the Management API, or (None, short error). Never includes key values."""
    mk = env.get("XAI_MANAGEMENT_KEY")
    if not mk:
        return None, None
    team = env.get("XAI_TEAM_ID")
    step = "team lookup"
    try:
        if not team:
            ak = env.get("XAI_API_KEY")
            if not ak:
                return None, "set XAI_TEAM_ID (or XAI_API_KEY) to find your team"
            team = get(API_BASE + "/v1/api-key", ak).get("team_id")
            if not team:
                return None, "no team_id from /v1/api-key"
        step = "balance"
        d = get(f"{MGMT_BASE}/v1/billing/teams/{team}/prepaid/balance", mk)
        return -int(d.get("total", {}).get("val", 0)) / 100, None
    except Exception as e:
        code = getattr(e, "code", None)
        if code in (401, 403):
            return None, BalanceDenied(code, step)
        return None, f"balance fetch failed ({code or type(e).__name__})"


class BalanceDenied(str):
    """401/403 from the balance (or team lookup) call: not an error for the user, never retried this session."""
    def __new__(cls, code, step="balance"):
        why = ("management key lacks billing access" if step == "balance" else "API key can't read its team id")
        o = super().__new__(cls, f"balance unavailable ({why}) · showing estimate")
        o.code, o.step = code, step
        return o


def spend_lines(bot, now=time.time):
    """Lines shown under the X spend in the status bar."""
    c, s = bot.cfg, bot.state
    out = [f"API ${s.api_run_spend():.2f} / ${effective_limit(c):.2f} limit [dim]({breakdown(s)})[/] · 5d ${s.spent_5d():.2f}"]
    bal = getattr(bot, "credit_balance", None)
    if bal is not None:
        usd, at = bal
        out.append(f"credits: ${usd:.2f} (xAI, as of {time.strftime('%H:%M', time.localtime(at))})")
    else:
        left = est_left(c, s)
        out.append(f"est. credits left: ${left:.2f}" if left is not None else "[dim]set: xbot config credits_start 25[/]")
        note = getattr(bot, "credit_note", None)
        if note:
            out.append(f"[dim]{note}[/]")
    return out


def parse_usd(raw):
    """'5', '$5', '5.00', 'off', '0' -> float (0 = off). Raises ValueError."""
    r = str(raw).strip().lower().replace(",", "")
    if r in ("off", "none", "no", "false", ""):
        return 0.0
    try:
        v = float(r.lstrip("$"))
    except ValueError:
        raise ValueError(f"expected a dollar amount like 5, $5 or off, got {raw!r}") from None
    if v < 0 or v != v or v == float("inf"):
        raise ValueError("must be >= 0 (0 or off disables)")
    return round(v, 4)


def parse_limit(raw):
    """Spend limit: a positive dollar amount only ('5', '$5', '5.00'); it can't be turned off."""
    r = str(raw).strip().lower()
    if r in ("off", "none", "no", "false", "0", "$0") :
        raise ValueError("the spend limit is always on and can't be turned off; give a positive amount, e.g. 5")
    v = parse_usd(raw)
    if v <= 0:
        raise ValueError("the spend limit must be a positive amount, e.g. 5")
    return v


def limit_summary(cfg, state):
    lim = effective_limit(cfg)
    dflt = " (default)" if lim == DEFAULT_LIMIT and getattr(cfg, "spend_limit", 0) in (DEFAULT_LIMIT, 0) else ""
    return (f"spend limit ${lim:.2f}{dflt} · spent ${state.api_run_spend():.4f} this session ({breakdown(state)}) · "
            f"left ${max(0.0, lim - state.api_run_spend()):.2f} · last 5 days ${state.spent_5d():.2f} (X + Grok, not part of the limit)")
