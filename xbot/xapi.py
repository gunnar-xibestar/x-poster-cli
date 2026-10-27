"""X API v2 layer behind an interface. DryRunX makes no network calls."""
import itertools, os
from abc import ABC, abstractmethod


class XError(RuntimeError):
    pass


class XNetError(XError):
    """Network failure talking to X (connection reset, timeout, broken response) after one retry."""


NET_RETRY_DELAY = 1.5  # seconds before the single retry


MEDIA_PARAMS = {"expansions": "attachments.media_keys,referenced_tweets.id,referenced_tweets.id.attachments.media_keys",
                "media.fields": "url,preview_image_url,type,variants,width,height,duration_ms"}
MEDIA_URL_RE = __import__("re").compile(r"(?:x|twitter)\.com/[^/]+/status/(\d+)/(photo|video)/\d", __import__("re").I)


def _media_item(m):
    url = m.get("url")
    if m.get("type") in ("video", "animated_gif"):
        from .video import pick_variant
        url = pick_variant(m.get("variants")) or url or m.get("preview_image_url")  # mp4 closest to 832 kbps
    out = {"type": m.get("type", "photo"), "url": url}
    mp4 = [{"url": v["url"], "bit_rate": v.get("bit_rate", 0), "content_type": "video/mp4"}
           for v in m.get("variants") or [] if v.get("content_type") == "video/mp4" and v.get("url")]
    if mp4:
        out["variants"] = mp4  # play-time pick: highest bitrate that fits the terminal
    for k in ("preview_image_url", "width", "height", "duration_ms"):
        if m.get(k):
            out[k] = m[k]
    return out


def _post_media(p, by_key):
    """Media of one post: attachments.media_keys, media keys / photo-video links in entities.urls."""
    keys = list((p.get("attachments") or {}).get("media_keys") or [])  # any media key = media
    items, linked = [], []
    nt = p.get("note_tweet") or {}  # long posts: full text + entities live here, past the truncated text
    urls = list((p.get("entities") or {}).get("urls") or []) + list((nt.get("entities") or {}).get("urls") or [])
    for u in urls:
        if u.get("media_key"):
            keys.append(u["media_key"])
            continue
        mm = MEDIA_URL_RE.search(u.get("expanded_url") or "")
        if mm or (u.get("display_url") or "").startswith("pic.twitter.com"):
            linked.append({"type": mm.group(2) if mm else "photo", "url": None,
                           **({"post_id": mm.group(1)} if mm else {})})
    for k in dict.fromkeys(keys):
        items.append(_media_item(by_key[k]) if k in by_key else {"type": "photo", "url": None})
    return items or linked


def attach_media(resp):
    """Copy includes.media onto each post as p['media'] = [{'type', 'url'}] (url = best direct link).
    Also covers media only reachable via entities.urls and media of a quoted post."""
    inc = resp.get("includes") or {}
    by_key = {m.get("media_key"): m for m in inc.get("media", [])}
    tweets = {t.get("id"): t for t in inc.get("tweets", [])}
    posts = resp.get("data", []) or []
    for p in posts:
        items = _post_media(p, by_key)
        if not items:
            for r in p.get("referenced_tweets") or []:
                if r.get("type") == "quoted" and r.get("id") in tweets:
                    items = [dict(i, post_id=i.get("post_id") or r["id"]) for i in _post_media(tweets[r["id"]], by_key)]
                    if items:
                        break
        if items:
            p["media"] = items
        if (p.get("note_tweet") or {}).get("text"):
            p["text"] = p["note_tweet"]["text"]  # show the whole long post
        p.pop("attachments", None)
    return posts


def media_url(p):
    """URL for the single [media] link: first media item's direct URL, else the post's media viewer."""
    ms = p.get("media") or []
    if not ms:
        return None
    if ms[0].get("url"):
        return ms[0]["url"]
    kind = "video" if ms[0].get("type") in ("video", "animated_gif") else "photo"
    return f"https://x.com/i/status/{ms[0].get('post_id') or p['id']}/{kind}/1"


class XClient(ABC):
    @abstractmethod
    def me(self) -> str: ...
    @abstractmethod
    def mentions(self, since_id=None) -> list[dict]: ...
    @abstractmethod
    def post(self, text, in_reply_to=None) -> str: ...
    @abstractmethod
    def search_recent(self, query, max_results=10, since_id=None, until_id=None) -> list[dict]:
        """Return posts as dicts: id, text, author_id, conversation_id, username (if expanded)."""


class DryRunX(XClient):
    def __init__(self, fake_mentions=None, fake_search=None):
        self.fake_mentions = list(fake_mentions or [])
        self.fake_search = list(fake_search or [])
        self.searches = []
        self.sent = []
        self._ids = itertools.count(9_000_000_000_000_000_001)

    def me(self):
        return "dryrun-user"

    def like(self, tweet_id, bearer=None):
        self.likes = getattr(self, "likes", []) + [str(tweet_id)]; return True

    def mute(self, target_id):
        self.muted = getattr(self, "muted", []) + [target_id]; return True

    def unmute(self, target_id):
        self.muted = [m for m in getattr(self, "muted", []) if m != target_id]; return True

    def user_id(self, handle):
        return "dry-" + handle

    def mentions(self, since_id=None):
        out, self.fake_mentions = self.fake_mentions, []
        return out

    def search_recent(self, query, max_results=10, since_id=None, until_id=None):
        self.search_calls = getattr(self, "search_calls", []) + [{"since_id": since_id, "until_id": until_id}]
        if until_id is not None:
            older = [p for p in self.fake_search if int(p["id"]) < int(until_id)]
            out = older[:max_results]
            self.fake_search = [p for p in self.fake_search if p not in out]
            return out
        self.searches.append(query)  # primary (newer) searches only; backfill calls are in search_calls
        pool = [p for p in self.fake_search if since_id is None or int(p["id"]) > int(since_id)]
        out = pool[:max_results]
        self.fake_search = [p for p in self.fake_search if p not in out]
        return out

    def post(self, text, in_reply_to=None):
        tid = str(next(self._ids))
        self.sent.append({"id": tid, "text": text, "in_reply_to": in_reply_to})
        return tid


class RealX(XClient):
    """OAuth 1.0a user context. Needs X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET."""
    BASE = "https://api.x.com/2"

    def __init__(self):
        from requests_oauthlib import OAuth1Session
        missing = [k for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET") if not os.environ.get(k)]
        if missing:
            raise XError(f"missing X credentials: {', '.join(missing)}")
        self.s = OAuth1Session(os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
                               os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_TOKEN_SECRET"])
        self._uid = None

    def _req(self, method, path, sleep=None, **kw):
        import time, requests
        sleep = sleep or time.sleep
        tries = 2 if method == "GET" else 1  # never auto-retry a POST: it may already have gone through
        for i in range(tries):
            try:
                r = self.s.request(method, self.BASE + path, timeout=30, **kw)
                break
            except requests.RequestException as e:  # ConnectionError, Timeout, ChunkedEncodingError, ...
                if i + 1 < tries:
                    sleep(NET_RETRY_DELAY); continue
                what = "connection reset" if isinstance(e, requests.ConnectionError) else type(e).__name__
                raise XNetError(f"X {what} on {method} {path.split('?')[0]}, try F5 again") from None
        if r.status_code >= 400:
            body = r.text[:300]
            hint = {401: "auth failed", 402: "out of X API credits", 403: "forbidden (tier/permissions; unsolicited replies are blocked unless the author summoned you)",
                    429: "rate limited"}.get(r.status_code, "error")
            raise XError(f"X API {r.status_code} {hint}: {body}")
        return r.json()

    def me(self):
        if not self._uid:
            self._uid = self._req("GET", "/users/me")["data"]["id"]
        return self._uid

    def like(self, tweet_id, bearer=None):
        """POST /2/users/:id/likes. bearer = OAuth 2.0 user token (like.write); else OAuth 1.0a user context."""
        body = {"tweet_id": str(tweet_id)}
        if bearer:
            import requests
            h = {"Authorization": f"Bearer {bearer}"}
            me = requests.get(self.BASE + "/users/me", headers=h, timeout=30)
            if me.status_code >= 400:
                raise XError(f"X API {me.status_code} {'rate limited' if me.status_code == 429 else 'error'}")
            r = requests.post(self.BASE + f"/users/{me.json()['data']['id']}/likes", headers=h, json=body, timeout=30)
            if r.status_code >= 400:
                raise XError(f"X API {r.status_code} {'rate limited' if r.status_code == 429 else 'forbidden' if r.status_code == 403 else 'error'}")
            return bool(r.json().get("data", {}).get("liked"))
        return bool(self._req("POST", f"/users/{self.me()}/likes", json=body)["data"].get("liked"))

    def access_level(self):
        """App permission of the OAuth 1.0a token from the x-access-level header (read / read-write / ...)."""
        r = self.s.request("GET", self.BASE + "/users/me", timeout=30)
        return r.headers.get("x-access-level", ""), r.status_code

    def mute(self, target_id):
        """POST /2/users/:id/muting (OAuth 1.0a user context or OAuth 2.0 user token)."""
        return self._req("POST", f"/users/{self.me()}/muting", json={"target_user_id": str(target_id)})["data"].get("muting")

    def unmute(self, target_id):
        """DELETE /2/users/:source_user_id/muting/:target_user_id."""
        return self._req("DELETE", f"/users/{self.me()}/muting/{target_id}")["data"].get("muting") is False

    def user_id(self, handle):
        """GET /2/users/by/username/:username (a billed User read)."""
        return self._req("GET", f"/users/by/username/{handle}")["data"]["id"]

    def mentions(self, since_id=None, cap=100):
        """All new mentions since since_id, following next_token pages, up to cap."""
        params = {"max_results": 100, "tweet.fields": "note_tweet,author_id,conversation_id,created_at,public_metrics,context_annotations,entities,possibly_sensitive,withheld,attachments,referenced_tweets",
                  **MEDIA_PARAMS}
        if since_id:
            params["since_id"] = since_id
        out = []
        while len(out) < cap:
            r = self._req("GET", f"/users/{self.me()}/mentions", params=params)
            out.extend(attach_media(r))
            tok = r.get("meta", {}).get("next_token")
            if not tok:
                break
            params["pagination_token"] = tok
        return out[:cap]

    def get_post(self, pid):
        """GET /2/tweets/:id with media (fresh video URLs after a 403)."""
        r = self._req("GET", f"/tweets/{pid}", params={"tweet.fields": "attachments,entities,referenced_tweets", **MEDIA_PARAMS})
        r["data"] = [r["data"]] if isinstance(r.get("data"), dict) else []
        posts = attach_media(r)
        return posts[0] if posts else None

    def search_recent(self, query, max_results=10, since_id=None, until_id=None):
        params = {"query": query, "max_results": max(10, min(100, max_results)),
                  "tweet.fields": "note_tweet,author_id,conversation_id,created_at,public_metrics,context_annotations,entities,possibly_sensitive,withheld,attachments,referenced_tweets",
                  **MEDIA_PARAMS}
        if since_id:
            params["since_id"] = since_id
        if until_id:
            params["until_id"] = until_id  # older than this id (search/recent covers last 7 days)
        r = self._req("GET", "/tweets/search/recent", params=params)
        return attach_media(r)  # author name/handle come from free oEmbed, not paid user expansions

    def post(self, text, in_reply_to=None):
        body = {"text": text}
        if in_reply_to:
            body["reply"] = {"in_reply_to_tweet_id": str(in_reply_to)}
        return self._req("POST", "/tweets", json=body)["data"]["id"]
