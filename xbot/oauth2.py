"""`xbot login`: OAuth 2.0 Authorization Code + PKCE for user-context X API calls (likes)."""
import base64, hashlib, json, os, secrets, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

AUTH_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
SCOPES = "tweet.read users.read like.write offline.access"
PORT = 8765
REDIRECT = f"http://127.0.0.1:{PORT}/callback"
SETUP_STEPS = f"""xbot login needs an X developer app with OAuth 2.0:
  1. developer.x.com > your Project > your App > User authentication settings > Set up / Edit
  2. App permissions: Read and write
  3. Type of App: Native App (public client; no secret)  [or Web App = confidential: then also set X_CLIENT_SECRET]
  4. Callback URI / Redirect URL: {REDIRECT}
  5. Website URL: any URL you own (required by the form), then Save
  6. Keys and tokens > OAuth 2.0 Client ID: add X_CLIENT_ID=<id> to ~/.config/xbot/env (chmod 600)
  7. Run: xbot login"""


def tokens_path():
    from .config import CONFIG_DIR
    return Path(CONFIG_DIR) / "tokens.json"


def pkce_pair():
    v = secrets.token_urlsafe(64)[:96]
    c = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")
    return v, c


def authorize_url(client_id, challenge, state):
    q = {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "scope": SCOPES,
         "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    return AUTH_URL + "?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)


def _register(tok):
    from .secure import register
    for k in ("access_token", "refresh_token"):
        if tok.get(k):
            register(tok[k])


def save_tokens(tok, now=time.time):
    from .secure import write_private
    t = dict(tok)
    if "expires_in" in t:
        t["expires_at"] = int(now() + int(t.pop("expires_in")))
    _register(t)
    write_private(tokens_path(), json.dumps(t))
    return t


def load_tokens():
    p = tokens_path()
    try:
        t = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    _register(t)
    return t if t.get("access_token") else None


def has_scope(tok, scope="like.write"):
    return bool(tok) and scope in (tok.get("scope") or "").split()


def _post(post, data, client_id, client_secret):
    kw = {"data": data, "headers": {"Content-Type": "application/x-www-form-urlencoded"}, "timeout": 30}
    if client_secret:
        kw["auth"] = (client_id, client_secret)
    r = post(TOKEN_URL, **kw)
    if getattr(r, "status_code", 200) >= 400:
        from .secure import redact
        raise RuntimeError(f"X token endpoint {r.status_code}: {redact(r.text[:200])}")
    return r.json()


def refresh_if_needed(tok=None, post=None, now=time.time, client_id=None, client_secret=None):
    """Return a valid token dict (refreshed + saved when within 60 s of expiry), or None."""
    tok = tok or load_tokens()
    if not tok:
        return None
    if tok.get("expires_at", 0) - 60 > now():
        return tok
    if not tok.get("refresh_token"):
        return None
    import requests
    cid = client_id or os.environ.get("X_CLIENT_ID")
    new = _post(post or requests.post, {"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                        "client_id": cid}, cid, client_secret or os.environ.get("X_CLIENT_SECRET"))
    new.setdefault("refresh_token", tok["refresh_token"]); new.setdefault("scope", tok.get("scope", ""))
    return save_tokens(new, now)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        self.server.result = {k: v[0] for k, v in q.items()}
        self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
        self.wfile.write(b"<h3>xbot: login received. You can close this tab.</h3>")

    def log_message(self, *a):  # never log the code
        pass


def login(client_id=None, client_secret=None, open_url=None, post=None, out=print, timeout=300, port=PORT):
    cid = client_id or os.environ.get("X_CLIENT_ID")
    sec = client_secret if client_secret is not None else os.environ.get("X_CLIENT_SECRET")
    if not cid:
        out(SETUP_STEPS); return 2
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    srv = HTTPServer(("127.0.0.1", port), _Handler)
    srv.result = None; srv.timeout = 1
    url = authorize_url(cid, challenge, state)
    if open_url is None:
        from .opener import open_url as open_url
    out("xbot login: approve xbot in your browser (opening it now)…")
    threading.Thread(target=lambda: open_url(url), daemon=True).start()
    end = time.time() + timeout
    try:
        while srv.result is None and time.time() < end:
            srv.handle_request()
    finally:
        srv.server_close()
    res = srv.result or {}
    if res.get("state") != state or not res.get("code"):
        out("xbot login: no valid authorization received (" + (res.get("error") or "timed out or state mismatch") + ")")
        return 1
    import requests
    tok = _post(post or requests.post, {"grant_type": "authorization_code", "code": res["code"], "redirect_uri": REDIRECT,
                                        "code_verifier": verifier, "client_id": cid}, cid, sec)
    t = save_tokens(tok)
    out("xbot login: saved tokens (0600) to " + str(tokens_path()) + " · scopes: " + (t.get("scope") or "?"))
    return 0 if has_scope(t) else 3
