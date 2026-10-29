"""Grok via OpenAI SDK (xAI is OpenAI-compatible). Fatal auth/credit errors are not retried."""
import os


class LLMFatal(RuntimeError):
    """Auth / credit / permission problem: bot should pause, not retry."""


class LLMError(RuntimeError):
    pass


class LLMTimeout(LLMError):
    """Grok did not answer within GROK_TIMEOUT_S (big batch on a slow model). Retried on the next refresh."""
    def __init__(self, msg, seconds):
        super().__init__(msg)
        self.seconds = seconds


GROK_TIMEOUT_S = 180  # per Grok request; batches of several posts on grok-4.x can take over a minute


class LLMRateLimited(LLMError):
    """xAI 429 'Too many requests' (e.g. a key limited to 1 request/minute). Back off, retry later."""
    def __init__(self, msg, retry_after=60):
        super().__init__(msg)
        self.retry_after = retry_after


# Text models xbot supports (docs.x.ai/docs/models, checked 2026-10-25). xbot only calls chat/completions,
# so an API key restricted to the chat endpoint is enough.
SUPPORTED_MODELS = ("grok-4.7", "grok-4.6", "grok-4.5")


class GrokLLM:
    def __init__(self, model, base_url):
        from openai import OpenAI
        key = os.environ.get("XAI_API_KEY")
        if not key:
            raise LLMFatal("XAI_API_KEY not set (env or ~/.config/xbot/env)")
        self.model = model
        self.client = OpenAI(api_key=key, base_url=base_url, max_retries=0, timeout=GROK_TIMEOUT_S)

    def complete(self, system, user):
        import openai
        try:
            r = self.client.chat.completions.create(
                model=self.model, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
            from .credits import cost_from_usage
            self.last_cost_usd = cost_from_usage(self.model, getattr(r, "usage", None))
            return (r.choices[0].message.content or "").strip()
        except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
            raise LLMFatal(f"xAI auth/permission/credit error ({e.status_code}): {_msg(e)}") from None
        except openai.APIStatusError as e:
            if e.status_code in (402, 429) and "credit" in _msg(e).lower():
                raise LLMFatal(f"xAI credit exhausted ({e.status_code}): {_msg(e)}") from None
            if e.status_code == 429:
                raise LLMRateLimited("xAI 429: too many requests for this API key (its requests-per-minute limit)",
                                     _retry_after(e)) from None
            raise LLMError(f"xAI {e.status_code}: {_msg(e)}") from None
        except openai.APITimeoutError:  # subclass of APIConnectionError: must come first
            raise LLMTimeout(f"Grok timed out after {GROK_TIMEOUT_S}s", GROK_TIMEOUT_S) from None
        except openai.APIConnectionError as e:
            if _is_timeout(e):
                raise LLMTimeout(f"Grok timed out after {GROK_TIMEOUT_S}s", GROK_TIMEOUT_S) from None
            url = str(self.client.base_url)
            local = any(h in url for h in ("127.0.0.1", "localhost", "[::1]"))
            raise LLMError(f"cannot reach {url}" + (" (local proxy down?)" if local else " (network error)")) from None


def _is_timeout(e):
    """A connection error caused by a read/connect timeout (httpx/httpx2 *Timeout*, socket TimeoutError)."""
    c, seen = e, 0
    while c is not None and seen < 10:
        if isinstance(c, TimeoutError) or "Timeout" in type(c).__name__:
            return True
        c, seen = c.__cause__ or c.__context__, seen + 1
    return False


def _retry_after(e, default=60):
    try:
        v = float(e.response.headers.get("retry-after"))
        return max(5, min(600, v))
    except Exception:
        return default


def _msg(e):
    """One readable line: the API's error message, not a raw dict dump."""
    try:
        b = e.body
        if isinstance(b, dict):
            b = b.get("error", b)
            if isinstance(b, dict):
                b = b.get("message") or b
        s = " ".join(str(b if b else e.message).split())
        return s if len(s) <= 300 else s[:299] + "…"
    except Exception:
        return "unknown"


class FakeLLM:
    def __init__(self, replies=None, fail=None):
        self.replies = list(replies or [])
        self.calls = []
        self.fail = fail
        self.cost = 0.0  # usd charged per call (tests)
        self.last_cost_usd = 0.0

    def complete(self, system, user):
        self.calls.append((system, user))
        self.last_cost_usd = self.cost
        if self.fail:
            raise self.fail
        return self.replies.pop(0) if self.replies else f"fake draft #{len(self.calls)}"
