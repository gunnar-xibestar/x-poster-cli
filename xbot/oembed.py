"""Free author lookup via X's public oEmbed endpoint (no API credits).
Verified 2026-10-24: publish.twitter.com 301s to publish.x.com; url=https://twitter.com/i/status/<id> works
without knowing the handle and returns author_name (display name) + author_url (https://x.com/<handle>)."""
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

ENDPOINT = "https://publish.x.com/oembed"
UA = "xbot/0.1 (personal terminal console; oEmbed author lookup)"


def fetch_author(tweet_id, get=None, timeout=5):
    """Return {'name', 'username'} or None. One attempt, short timeout, no retries."""
    if get is None:
        import requests
        get = requests.get
    try:
        r = get(ENDPOINT, params={"url": f"https://twitter.com/i/status/{tweet_id}", "omit_script": 1, "dnt": "true"},
                headers={"User-Agent": UA}, timeout=timeout)
        if getattr(r, "status_code", 0) != 200:
            return None
        d = r.json()
        handle = urlparse(d.get("author_url", "")).path.strip("/").split("/")[0]
        if not handle:
            return None
        return {"name": d.get("author_name") or handle, "username": handle}
    except Exception:
        return None


def fetch_many(ids, fetch=fetch_author, workers=3):
    """Concurrent lookups (small pool). Returns {id: result_or_None}."""
    ids = list(dict.fromkeys(ids))
    if not ids:
        return {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return dict(zip(ids, ex.map(fetch, ids)))
