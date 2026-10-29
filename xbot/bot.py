"""Bot core: polls mentions + search, drafts via Grok, queues for your approval, sends on approve.

Owns the tick loop, filters (tags/topics/words/mentioners), mute/block/hide, spend limit,
and every slash command that isn't purely UI. The Textual app (app.py) calls into here;
this module never talks to Textual widgets directly.
"""
import random, re
from .textutil import clip
from pathlib import Path
from .commands import Command
from .llm import LLMFatal, LLMError, LLMRateLimited, LLMTimeout, SUPPORTED_MODELS
from .queue import DraftQueue
from .xapi import media_url

SHARE_TEXT = ("I am posting from the terminal, you can too, checkout this cli tool by xibestar "
              "https://github.com/gunnar-xibestar/x-poster-cli")


def share_url(text=SHARE_TEXT):
    """X compose intent with the share text prefilled (opened in the browser, never posted via the API)."""
    from urllib.parse import quote
    return "https://x.com/intent/post?text=" + quote(text, safe="")
from .state import BotState, COST_POST, COST_POST_URL, COST_SUMMONED_REPLY, COST_READ, COST_OWNED_READ, COST_MUTE, COST_UNMUTE, COST_USER_LOOKUP
import json
from collections import Counter
from .safety import detail as filter_detail, QUERY_EXCLUDES, reasons as filter_reasons, ALL_TOPICS, TOPICS as FILTER_TOPICS
from .tags import DEFAULT_TAXONOMY, UNTAGGED, tag_post, build_query, x_labels, label_ids, retag
from .config import x_keys_present
from .xapi import DryRunX, XError

URL_RE = re.compile(r"(https?://|www\.)\S+|\b[\w-]+\.(com|io|ai|dev|org|net|co)\b", re.I)


class Bot:
    def __init__(self, config, llm, x, log, real_x_factory=None, save_config=None, rng=None, state_dir=None, clock=None,
                 llm_factory=None):
        self.cfg, self.llm, self.log = config, llm, log
        self.limit_exit = None  # set when the per-run xAI spend limit is reached (app exits)
        self.on_limit_exit = None
        self.credit_balance = None  # (usd, epoch) from the xAI Management API
        self.dry_x = x if isinstance(x, DryRunX) else DryRunX()
        self.real_x = None if isinstance(x, DryRunX) else x
        self.real_x_factory = real_x_factory
        self.save_config = save_config or (lambda: None)
        sd = Path(state_dir) if state_dir else log.dir
        self.state_dir = Path(sd)
        from .style import StyleStore
        self.style = StyleStore(Path(sd) / "style_examples.jsonl")
        self.queue = DraftQueue(sd / "queue.json")
        self.state = BotState(sd / "state.json", **({"clock": clock} if clock else {}))
        self.session_start = (clock or __import__("time").time)()
        self._session_ended = None
        if self.state.grok_run_spend or self.state.x_run_spend:
            self.state.reset_run_spend()  # every session starts at $0 (e.g. after a hard kill)
        self.paused = False
        self.stopped = False
        self.since_id = None
        self.search_since_id = None
        self.search_oldest_id = None  # oldest post id ever fetched by search (backfill until_id)
        self.ticks = 0
        self.rng = rng or random.Random()
        self._full_logged = False
        self._skipped = set()
        self._last_kind = None  # drafting scheduler: alternates queues on ties
        self.llm_backoff_until = 0.0  # xAI 429 or own pacing: no Grok calls before this time (memory only: cleared on restart)
        self._draft_lock = __import__("threading").Lock()
        self._llm_calls = []  # (clock time, manual?) of recent Grok calls (pacing window)
        self.auto_wait_until = 0.0  # own pacing: no AUTO Grok calls before this time
        self._pace_logged = False
        self.last_draft_error = None  # short reason the last draft failed (shown in the g editor)
        self._clock = clock or __import__("time").time
        self.last_check = None
        self.author_fetch = None  # callable(tweet_id) -> {'name','username'}|None; default oEmbed
        self.opener = None  # callable(url, done) -> async open; default opener.open_url_async
        self.llm_factory = llm_factory
        self.found_path = sd / "found.json"
        self.found = []  # recent found posts (dicts), newest last
        if self.found_path.exists():
            try:
                self.found = [{"id": f["id"], "username": f.get("username", f.get("author")), "text": f["text"],
                               "created_at": f.get("created_at"), "source": f.get("source"),
                               "replied": f.get("replied", False), "name": f.get("name"),
                               "public_metrics": f.get("public_metrics"), "tags": f.get("tags", []), "xlabels": f.get("xlabels") or {},
                               "author_id": f.get("author_id"), "author_lookup": f.get("author_lookup"),
                               **({"media": f["media"]} if f.get("media") else {}),
                               **({"user_hidden": f["user_hidden"], "hide_why": f.get("hide_why")} if f.get("user_hidden") else {})} for f in json.loads(self.found_path.read_text())["posts"]]
            except Exception:
                self.found = []
        from .safety import set_topic_edits
        set_topic_edits(self.cfg.topic_edits)
        if not self.cfg.draft_batch_migrated:  # old default 8 timed out on grok-4.x; a value you set stays
            if self.cfg.draft_batch == 8:
                self.cfg.draft_batch = 4
            self.cfg.draft_batch_migrated = True
            try:
                self.save_config()
            except Exception:
                pass
        if not self.cfg.x_flags_migrated:  # X's flags used to be part of "adult"; keep them on for old configs
            if "adult" in self.cfg.filter_topics and "x-flags" not in self.cfg.filter_topics:
                self.cfg.filter_topics.append("x-flags")
            self.cfg.x_flags_migrated = True
            try:
                self.save_config()
            except Exception:
                pass
        self.filtered_path = sd / "filtered.json"
        self.filtered = []  # search posts the filter dropped at fetch time, newest last
        if self.filtered_path.exists():
            try:
                self.filtered = json.loads(self.filtered_path.read_text())
            except Exception:
                self.filtered = []
        for p in self.found:  # retag with the current taxonomy
            p["tags"] = retag(p, self.taxonomy)
        self._compact_found()
        self._x_err_logged = None
        if self.llm is None:
            self.log.event("warn", "XAI_API_KEY missing: running X-only (search/mentions listed in /found, no drafting). "
                           "Add key then /grok on")

    def reads_live(self):
        r = self.cfg.reads_live
        return x_keys_present() if r is None else bool(r)

    @property
    def rx(self):
        """Client for reads (mentions/search/me)."""
        return self._real() if self.reads_live() else self.dry_x

    @property
    def x(self):
        """Client for sends."""
        if self.cfg.dry_run:
            return self.dry_x
        return self._real()

    def _real(self):
        if self.check_spend_limit():  # combined X + Grok session limit: no further X request
            from .xapi import XError as _XErr
            e = _XErr(self.limit_exit); e.logged = True
            raise e
        if self.real_x is None:
            try:
                self.real_x = self.real_x_factory()
            except XError as e:
                if self._x_err_logged != str(e):
                    self._x_err_logged = str(e)
                    self.log.event("error", f"{e} -- add them to ~/.config/xbot/env and restart, or /dryrun on")
                e.logged = True
                raise
            if self.state.me_id and hasattr(self.real_x, "_uid"):
                self.real_x._uid = self.state.me_id  # cached own id: skip GET /users/me
        return self.real_x

    def _cache_me(self, x):
        uid = getattr(x, "_uid", None)
        if uid and uid != self.state.me_id:
            self.state.me_id = uid; self.state.save()

    # ---- spend ---------------------------------------------------------
    def _charge(self, usd, live):
        if live and usd:
            self.state.add_spend(usd)
            self.check_spend_limit()

    def check_spend_limit(self):
        """Per-run xAI limit: once reached, reset the counter (saved atomically), stop the bot and set
        limit_exit to the message the app prints after exiting. Returns True when reached."""
        if getattr(self, "limit_exit", None):
            return True
        from .credits import limit_reached, limit_message, effective_limit
        if not limit_reached(self.cfg, self.state):
            return False
        spent = self.state.api_run_spend()
        self.limit_exit = limit_message(effective_limit(self.cfg), spent)
        self.paused = True
        try:
            self.queue._save()
        except Exception:
            pass
        self.log.event("error", self.limit_exit)
        if getattr(self, "on_limit_exit", None):
            self.on_limit_exit(self.limit_exit)
        return True

    def end_session(self):
        """On any exit: reset session spend to $0 (saved atomically; per-day totals kept) and return the
        console summary. Safe to call more than once (returns the same summary)."""
        if self._session_ended is None:
            from .credits import session_summary, effective_limit
            clk = getattr(self.state, "clock", None) or __import__("time").time
            from .credits import breakdown
            self._session_ended = session_summary(clk() - self.session_start, self.state.api_run_spend(),
                                                  effective_limit(self.cfg), self.limit_exit, breakdown(self.state),
                                                  last5=self.state.spent_5d())
            self.state.reset_run_spend()
        return self._session_ended

    def cap_hit(self):
        return self.cfg.daily_cap_usd > 0 and self.state.spent_today() >= self.cfg.daily_cap_usd

    # ---- drafting ------------------------------------------------------
    def system_prompt(self):
        return (f"{self.cfg.persona}\nTopics of interest: {', '.join(self.cfg.topics)}.\n"
                f"Write a single X post under {self.cfg.max_chars} characters. Output only the post text. "
                "Do not include links." + self._style_block())

    def _style_excluded(self):
        return {str(p["id"]) for p in self.found if p.get("user_hidden") or self.hidden(p)
                or (p.get("username") or "").lower() in self.cfg.blocked_authors}

    def _style_block(self):
        from .style import examples_block
        n = int(getattr(self.cfg, "style_examples", 0) or 0)
        return examples_block(self.style.load(), n, self._style_excluded()) if n > 0 else ""

    def learn_style(self, post_id, post_text, grok_text, final):
        """User edited a Grok draft and approved/saved it: keep (post, draft, final). Never hidden/filtered posts."""
        if not grok_text or not final or grok_text.strip() == final.strip():
            return False
        p = next((q for q in self.found if str(q["id"]) == str(post_id)), None)
        if p is not None and (p.get("user_hidden") or self.hidden(p) or self.filter_why(p)):
            return False
        if self.style.add(post_id, post_text, grok_text, final):
            self.log.event("info", "saved your edit as a style example (/style clear to forget)")
            return True
        return False

    def _xerr(self, e, prefix=""):
        from .xapi import XNetError
        if isinstance(e, XNetError):
            self.log.event("warn", f"{prefix}{e}"); return
        if not getattr(e, "logged", False):
            self.log.event("error", f"{prefix}{e}")
        elif prefix:
            self.log.event("error", f"{prefix}X credentials missing")

    @property
    def grok_on(self):
        return self.llm is not None

    def _remember(self, p, source):
        p = dict(p, source=source)
        p["tags"] = tag_post(p, self.taxonomy)
        p["xlabels"] = x_labels(p)
        self.state.feed_shown.append(str(p["id"]))  # shown now: at the end of the FIFO, never served again
        p.pop("context_annotations", None); p.pop("entities", None)
        self.found.append(p)
        self.found = self.found[-1000:]
        n = len(self.found)
        who = p.get("username") or p.get("author_id", "?")
        self.export()
        snip = clip(p["text"], 400)  # the feed wraps at its real width
        tg = f" {{{','.join(p['tags'])}}}" if p["tags"] else ""
        self.log.event("found", f"#{n} [{source}] …{p['id'][-6:]} @{who}: {snip}{tg}  https://x.com/i/status/{p['id']}",
                       tweet_id=p["id"], n=n, source=source, author=who, snippet=snip, tags=p["tags"],
                       blocked=self.is_blocked(p),
                       **({"media_url": media_url(p)} if p.get("media") else {}))

    def _found_line(self, n, p, **extra):
        who = p.get("username") or p.get("author_id", "?")
        snip = clip(p["text"], 400)  # the feed wraps at its real width
        self.log.feed_only("found", f"#{n} [{p.get('source')}] …{p['id'][-6:]} @{who}: {snip}  https://x.com/i/status/{p['id']}",
                           tweet_id=p["id"], n=n, source=p.get("source"), author=who, snippet=snip,
                           replied=bool(p.get("replied")), tags=p.get("tags", []), blocked=self.is_blocked(p),
                           **({"media_url": media_url(p)} if p.get("media") else {}), **extra)

    def replay_found(self):
        """Startup: redraw the current FIFO page (the last FEED_MAX served posts; the first page of saved posts
        when none were served yet). Mentions first, then suggestions; not re-logged to JSONL."""
        if not self.feed_found():
            return self.serve_saved()
        items = self.feed_found()
        allv = len(self.visible_found())
        if items:
            self.log.feed_only("info", f"replaying {len(items)} found posts"
                               + (f" (newest {len(items)} of {allv})" if allv > len(items) else "")
                               + (f" ({len(self.found) - allv} hidden by tag)" if allv < len(self.found) else ""))
        for src, title in (("mention", "Mentions"), ("search", "Suggested replies")):
            grp = [(n, p) for n, p in items if p.get("source") == src]
            if grp:
                self.log.feed_only("section", f"{title} ({len(grp)}) [replay]")
            for n, p in grp:
                self._found_line(n, p, replay=True)
        return len(items)

    def export(self):
        """Atomically write found posts (no secrets: only public post fields) to found.json."""
        posts = [{"n": i, "id": p["id"], "author": p.get("username") or p.get("author_id"), "text": p["text"],
                  "created_at": p.get("created_at"), "url": f"https://x.com/i/status/{p['id']}",
                  "source": p.get("source"), "replied": bool(p.get("replied")),
                  "name": p.get("name"), "public_metrics": p.get("public_metrics"), "tags": p.get("tags", []), "xlabels": p.get("xlabels") or {},
                  "author_id": p.get("author_id"), "author_lookup": p.get("author_lookup"),
                  "username": p.get("username"), **({"media": p["media"]} if p.get("media") else {}),
                  **({"user_hidden": p["user_hidden"], "hide_why": p.get("hide_why")} if p.get("user_hidden") else {})}
                 for i, p in enumerate(self.found, 1)]
        self.found_path.parent.mkdir(parents=True, exist_ok=True)
        from .secure import write_private
        write_private(self.found_path, json.dumps({"updated": __import__("time").strftime("%Y-%m-%dT%H:%M:%S%z"), "posts": posts}, indent=1))
        return len(posts)

    @property
    def taxonomy(self):
        return self.cfg.taxonomy or DEFAULT_TAXONOMY

    def _compact_found(self):
        """Startup: drop posts hidden for good (and their drafts), visible posts first, so the feed starts at #1."""
        gone = {str(p["id"]) for p in self.found if p.get("user_hidden") == "forever"}
        for d in self.queue.pending():
            if d.in_reply_to and str(d.in_reply_to) in gone:
                self.queue.set_status(d.id, "rejected")
        keep = [p for p in self.found if str(p["id"]) not in gone]
        vis = [p for p in keep if not self.hidden(p)]
        new = vis + [p for p in keep if self.hidden(p)]
        if [p["id"] for p in new] != [p["id"] for p in self.found]:
            self.found = new
            try:
                self.export()
            except Exception:
                pass

    def is_blocked(self, p):
        return (p.get("username") or "").lower() in self.cfg.blocked_authors

    def hidden(self, p):
        """Search posts with an excluded tag or blocked author are hidden; mentions never are."""
        if p.get("user_hidden"):
            return True
        return p.get("source") != "mention" and (
            self.is_blocked(p) or bool(self.filter_why(p)) or bool(set(label_ids(p)) & set(self.cfg.excluded_tags)))

    def visible_found(self):
        return [(n, p) for n, p in enumerate(self.found, 1) if not self.hidden(p)]

    # ---- FIFO feed: saved posts are served oldest first, FEED_MAX per F5 ----------------------------
    def _shown(self):
        return set(map(str, self.state.feed_shown))

    def mark_shown(self, ids):
        s = self._shown()
        new = [str(i) for i in ids if str(i) not in s]
        if new:
            keep = {str(p["id"]) for p in self.found}
            self.state.feed_shown = [i for i in self.state.feed_shown if str(i) in keep] + new
            try:
                self.state.save()
            except Exception:
                pass

    def feed_found(self):
        """The visible found posts loaded into the feed: the last FEED_MAX already served (found order)."""
        from .config import FEED_MAX
        s = self._shown()
        vis = [(n, p) for n, p in self.visible_found() if str(p["id"]) in s]
        return vis[-FEED_MAX:] if FEED_MAX > 0 else vis

    def saved_left(self):
        """Visible saved posts not served to the feed yet, oldest first."""
        s = self._shown()
        return [(n, p) for n, p in self.visible_found() if str(p["id"]) not in s]

    def serve_saved(self):
        """F5: show the next FEED_MAX not-yet-shown saved posts (oldest first). No X search, no Grok drafting.
        Returns how many were shown."""
        from .config import FEED_MAX
        left = self.saved_left()
        page = left[:FEED_MAX] if FEED_MAX > 0 else left
        if not page:
            return 0
        self.mark_shown([p["id"] for _, p in page])
        rest = len(left) - len(page)
        self.log.feed_only("section", f"Saved posts ({len(page)}) · oldest first · {rest} saved left")
        for n, p in page:
            self._found_line(n, p, replay=True)
        return len(page)

    def _fetch_author(self, tid):
        from .oembed import fetch_author
        return (self.author_fetch or fetch_author)(tid)

    def prefetch_authors(self, posts):
        """Fill username/name from free oEmbed for raw posts missing them (small pool, short timeout)."""
        if not self.cfg.oembed_prefetch:
            return
        from .oembed import fetch_many
        need = [p for p in posts if not p.get("username")]
        res = fetch_many([p["id"] for p in need], fetch=self._fetch_author, workers=3)
        for p in need:
            a = res.get(p["id"])
            if a:
                p.update(a); p["author_lookup"] = "ok"
            else:
                p["author_lookup"] = "failed"

    def lookup_author(self, n):
        """Lazy lookup for found post #n (blocking; call from a worker). Cached; never retried after failure."""
        p = self.found_post(n)
        if p.get("username") or p.get("author_lookup") == "failed":
            return p
        a = self._fetch_author(p["id"])
        if a:
            p.update(a); p["author_lookup"] = "ok"
        else:
            p["author_lookup"] = "failed"
        self.export()
        return p

    def _author_id_for(self, handle):
        for p in reversed(self.found):
            if (p.get("username") or "").lower() == handle and p.get("author_id"):
                return p["author_id"]
        return None

    def mute(self, handle, author_id=None):
        """Mute on the real X account (send=live) + block locally. Dry: log [DRY-MUTE] only."""
        handle = handle.lower().lstrip("@")
        self.set_blocked(set(self.cfg.blocked_authors) | {handle})
        aid = author_id or self._author_id_for(handle)
        if self.cfg.dry_run:
            self.cfg.muted_authors[handle] = {"id": aid, "live": False}; self.save_config()
            self.log.event("sent", f"[DRY-MUTE] @{handle} mute (real) not sent (send=dry); block (local) applied")
            return True
        if self.cap_hit():
            self.log.event("error", f"daily cap reached; mute (real) not sent; @{handle} block (local) only"); return False
        try:
            x = self.x
            if not aid:
                aid = x.user_id(handle); self._charge(COST_USER_LOOKUP, True)
            ok = x.mute(aid); self._charge(COST_MUTE, True); self._cache_me(x)
        except XError as e:
            self._mute_err(e, handle, "mute"); return False
        self.cfg.muted_authors[handle] = {"id": aid, "live": True}; self.save_config()
        self.log.event("sent", f"[LIVE] mute (real) @{handle}" + ("" if ok else " (X did not confirm)"))
        return True

    def like_post(self, n):
        """Like found post #n through the X API (never the browser). Returns (ok, one-line message).
        Uses an OAuth 2.0 user token with like.write (xbot login) if present, else the OAuth 1.0a user token."""
        from . import oauth2
        p = self.found_post(n); pid = str(p["id"])
        bearer = None
        tok = None
        try:
            tok = oauth2.refresh_if_needed()
        except Exception as e:
            return False, f"like not sent: token refresh failed ({clip(str(e), 80)}); run xbot login"
        if tok is not None:
            if not oauth2.has_scope(tok, "like.write"):
                return False, "like not sent: your X login lacks like.write; run xbot login to re-authorize"
            bearer = tok["access_token"]
        if self.cap_hit():
            return False, "like not sent: daily cap reached"
        x = self._real()
        if x is None:
            return False, "like not sent: no X credentials (add them to ~/.config/xbot/env or run xbot login)"
        try:
            ok = x.like(pid, bearer=bearer)
        except XError as e:
            m = str(e)
            if "429" in m:
                return False, "like not sent: X rate limit (429), try again in a few minutes"
            if "403" in m or "401" in m:
                return False, ("like not sent: X refused (" + ("401" if "401" in m else "403")
                               + "); the token needs write/like permission: set the app to Read and write and "
                                 "regenerate the access token, or run xbot login")
            return False, f"like not sent: {clip(m, 100)}"
        self._charge(COST_MUTE, True)  # User Interaction: Create
        self.log.event("sent", f"[LIVE] liked #{n} (post {pid})" + ("" if ok else " (X did not confirm)"))
        return True, f"liked #{n}"

    def unmute(self, handle):
        handle = handle.lower().lstrip("@")
        rec = self.cfg.muted_authors.get(handle)
        if rec is None:
            raise KeyError(f"@{handle} is not in the muted list")
        self.set_blocked(set(self.cfg.blocked_authors) - {handle})
        if rec.get("live") and not self.cfg.dry_run:
            try:
                x = self.x
                aid = rec.get("id") or x.user_id(handle)
                x.unmute(aid); self._charge(COST_UNMUTE, True)
            except XError as e:
                self._mute_err(e, handle, "unmute"); return False
            self.log.event("sent", f"[LIVE] unmute (real) @{handle}")
        elif rec.get("live"):
            self.log.event("warn", f"[DRY-UNMUTE] @{handle} block (local) removed; mute (real) still on X until /send live + /unmute")
            return True
        else:
            self.log.event("sent", f"[DRY-UNMUTE] @{handle}")
        self.cfg.muted_authors.pop(handle, None); self.save_config()
        return True

    def _mute_err(self, e, handle, verb):
        if getattr(e, "logged", False):
            msg = "X credentials missing"
        elif " 403" in str(e):
            msg = "X refused (403): this app/tier or token may lack mute permission (needs user-context auth with write access)"
        elif " 402" in str(e):
            msg = "X API credits exhausted (402)"
        elif " 401" in str(e):
            msg = "X auth failed (401)"
        else:
            msg = str(e)[:200]
        self.log.event("error", f"{verb} (real) @{handle} failed: {msg}" + (" -- block (local) only" if verb == "mute" else ""))

    def nav_order(self):
        """Found-post numbers in list order: mentions first, then suggestions; hidden excluded."""
        vis = self.feed_found()
        return [n for n, p in vis if p.get("source") == "mention"] + [n for n, p in vis if p.get("source") != "mention"]

    def tag_counts(self):
        return Counter(t for p in self.found for t in label_ids(p))

    def effective_query(self):
        base = self.cfg.search_query
        return self._with_safety(build_query(base, self.cfg.excluded_tags, self.taxonomy, self.cfg.search_query_limit,
                           blocked=self.cfg.blocked_authors))

    def hide_reasons(self, p):
        """Why the filter (topics, words, excluded tags) hides this post; blocks are not filter reasons."""
        why = ([f"hidden by you: {'; '.join(p['hide_why'])}" if p.get("hide_why") else "hidden by you"]
               if p.get("user_hidden") else [])
        why += filter_detail(p, self.cfg.filter_topics, self.cfg.filter_words) if self.cfg.auto_filter else []
        why += [f"tag {t}" for t in label_ids(p) if t in self.cfg.excluded_tags]
        return why

    STOP = set("about after again also another because been before being could does doing down every from have just like more most much only other over really same should some such than that their them then there these they this those through very want what when where which while with would your just will into been here http https".split())

    def hide_post(self, n, forever=True, why=None):
        """h on a card: hide found post #n (feed, suggestions, nav), drop its pending drafts, keep it seen.
        forever=True: never shown again and not listed in /hidden. Otherwise listed with `why`."""
        p = self.found_post(n)
        self.drop_prefill(p["id"])
        for q in self.found:  # same post can be in the feed twice (mention + search): hide every copy
            if str(q["id"]) == str(p["id"]):
                q["user_hidden"] = "forever" if forever else True
                if why:
                    q["hide_why"] = list(why)
        if p["id"] not in self.state.seen:
            self.state.seen.append(p["id"]); self.state.save()
        dropped = 0
        for d in self.queue.pending():
            if str(d.in_reply_to) == str(p["id"]):
                self.queue.reject(d.id); dropped += 1
        self.export()
        who = p.get("username") or p.get("author_id", "?")
        self.log.event("align", f"#{n} @{who} hidden" + (" for good" if forever else f" ({'; '.join(why or [])})")
                       + (f" · dropped {dropped} draft(s)" if dropped else ""))
        return dropped

    def filter_options(self, p):
        """Candidate filters for 'posts like this': [(value, label)]. value = tag:X | topic:X | word:X."""
        import re
        out = []
        h = (p.get("username") or "").lower()
        if h and h not in self.cfg.blocked_authors:
            out.append((f"author:{h}", f"hide author @{h} (local block list)"))
        for t in label_ids(p):
            if t not in self.cfg.excluded_tags:
                out.append((f"tag:{t}", f"exclude tag {t}"))
        for t in ALL_TOPICS:
            if t not in self.cfg.filter_topics and filter_detail(p, [t], []):
                out.append((f"topic:{t}", f"hide broad topic {t}"))
        have = {w.lower() for w in self.cfg.filter_words}
        words = []
        for w in re.findall(r"[#$]?[A-Za-z][\w'-]{3,}", p.get("text", "")):
            lw = w.lower().strip("'")
            if lw in self.STOP or lw in have or lw in words or lw.startswith("http"):
                continue
            words.append(lw)
        for w in words[:8]:
            out.append((f"word:{w}", f"hide word {w}"))
        return out

    def apply_filter_options(self, values):
        """Apply checked filter options; return human-readable reasons."""
        why, tags, topics = [], set(self.cfg.excluded_tags), set(self.cfg.filter_topics)
        for v in values:
            kind, _, x = v.partition(":")
            if kind == "tag":
                tags.add(x); why.append(f"tag {x}")
            elif kind == "topic":
                topics.add(x); why.append(f"topic {x}")
            elif kind == "author":
                self.set_blocked(set(self.cfg.blocked_authors) | {x}); why.append(f"author @{x}")
            elif kind == "word":
                self.filter_cmd(f"hide '{x}'" if "'" not in x else f'hide "{x}"'); why.append(f'word "{x}"')
        if tags != set(self.cfg.excluded_tags):
            self.set_excluded(tags)
        if topics != set(self.cfg.filter_topics):
            self.set_filter_topics(topics)
        self.prune_prefill()
        return why

    def unhide_post(self, n):
        p = self.found_post(n)
        p.pop("user_hidden", None); p.pop("hide_why", None); self.export()
        self.log.event("align", f"#{n} restored (no longer hidden by you)")

    def _keep_filtered(self, p, why):
        self.drop_prefill(p["id"])
        who = p.get("username") or p.get("author_id", "?")
        self.filtered.append({"id": p["id"], "username": who, "text": p.get("text", ""), "why": why,
                              "batch": self._batch,
                              "url": f"https://x.com/i/status/{p['id']}"})
        self.filtered = self.filtered[-200:]
        from .secure import write_private
        write_private(self.filtered_path, json.dumps(self.filtered, indent=1))

    def hidden_list(self):
        """[(label, post, reasons)]: saved found posts the filter hides, then ones dropped at fetch time."""
        out = [(f"#{n}", p, self.hide_reasons(p)) for n, p in enumerate(self.found, 1)
               if p.get("user_hidden") != "forever" and (p.get("user_hidden") or p.get("source") != "mention" and self.hide_reasons(p))]
        out += [(f"h{i}", p, p.get("why", [])) for i, p in enumerate(self.filtered, 1)]
        return out

    def hidden_items(self, all_=False):
        items = self.hidden_list()
        if not all_:
            last = max([f.get("batch", 0) for f in self.filtered] + [0])
            items = [(l, p, w) for l, p, w in items
                     if (l.startswith("h") and last and p.get("batch") == last) or (l.startswith("#") and p.get("user_hidden"))]
        return items

    def show_hidden(self, all_=False):
        ev = self.log.event
        items = self.hidden_items(all_)
        if not items:
            ev("info", "nothing hidden by the filter" + ("" if all_ else " in the last check (try /hidden all)")); return
        self.log.event("section", f"Hidden by filter ({len(items)})" + (" · all" if all_ else " · last check · /hidden all for everything"))
        for label, p, why in items:
            who = p.get("username") or p.get("author_id", "?")
            ev("hidden", f"{label} @{who}: {clip(p.get('text', ''), 70)}\n"
                         f"      caught by: {'; '.join(why)}\n"
                         f"      https://x.com/i/status/{p['id']}")
        ev("info", "to bring a group back: /filter show <topic or word>  (tags: /include <tag>)")

    def filter_why(self, p):
        from .safety import builtin_reasons
        base = builtin_reasons(p)  # built-in blocklist: applied even if filters are edited or off
        if not self.cfg.auto_filter:
            return base
        return filter_reasons(p, self.cfg.filter_topics, self.cfg.filter_words) or base

    def _with_safety(self, res):
        q, added, dropped = res
        if not self.cfg.auto_filter:
            return q, added, dropped
        terms = []
        if "adult" in self.cfg.filter_topics or "spam" in self.cfg.filter_topics:
            terms.append(QUERY_EXCLUDES)
        terms += [f' -"{w}"' if not re.fullmatch(r"\w+", w) else f" -{w}" for w in self.cfg.filter_words]
        for t in terms:
            if t.strip() in q:
                continue
            if len(q) + len(t) <= self.cfg.search_query_limit:
                q += t; added += 1
            else:
                dropped += 1
        return q, added, dropped

    def filter_cmd(self, text):
        ev = self.log.event
        a = text.split(None, 1)
        sub = a[0].lower() if a else ""
        arg = a[1].strip() if len(a) > 1 else ""
        cfg = self.cfg
        if sub in ("", "list", "status"):
            from . import safety as sf
            kw = dict(FILTER_TOPICS)
            kw["adult"] = sf.ADULT_WORDS + [f"link {d}" for d in sf.ADULT_DOMAINS] + ["posts X marks sensitive"]
            kw["spam"] = sf.SPAM_PHRASES + ["👇 + a link"]
            on_t = [t for t in ALL_TOPICS if t in cfg.filter_topics]
            off_t = [t for t in ALL_TOPICS if t not in cfg.filter_topics]
            plain = (f"filter {'on' if cfg.auto_filter else 'off'} | topics: {', '.join(on_t) or 'none'} | "
                     f"words: {', '.join(cfg.filter_words) or 'none'}")
            ev("filter", plain, on=cfg.auto_filter, topics_on=on_t, topics_off=off_t,
               words=list(cfg.filter_words), tags=list(cfg.excluded_tags), mentioners=list(cfg.filtered_mentioners),
               skipped=(["promoted posts", "nsfw", "onlyfans", "porn", "ai girlfriend"]
                        if ("adult" in cfg.filter_topics or "spam" in cfg.filter_topics) else []) + list(cfg.filter_words))
            return
        if sub in ("on", "off"):
            cfg.auto_filter = sub == "on"; self.save_config(); ev("align", f"filter {sub}"); self.export(); return
        if sub == "why":
            n = int(arg.lstrip("#")) if arg.lstrip("#").isdigit() else 0
            if not 1 <= n <= len(self.found):
                raise KeyError("usage: /filter why <n>")
            why = self.filter_why(self.found[n - 1])
            why = filter_detail(self.found[n - 1], cfg.filter_topics, cfg.filter_words)
            ev("info", f"#{n}: " + (f"caught by {'; '.join(why)}" if why else "not filtered")); return
        if sub in ("edit", "reset"):
            from .safety import topic_words, set_topic_edits
            import shlex
            try:
                parts = shlex.split(arg)
            except ValueError:
                parts = arg.split()
            if not parts or parts[0].lower() not in ALL_TOPICS:
                raise KeyError(f"usage: /filter edit <topic> [+word] [-word]  topics: {', '.join(ALL_TOPICS)}")
            t = parts[0].lower()
            e = cfg.topic_edits.setdefault(t, {"add": [], "remove": []})
            if sub == "reset":
                cfg.topic_edits.pop(t, None)
            for it in parts[1:]:
                w = it[1:].lower().strip()
                if not w or it[0] not in "+-":
                    raise KeyError("put + before a word to add it, - to remove it, e.g. /filter edit war +drone -russia")
                if it[0] == "+":
                    if w in e["remove"]: e["remove"].remove(w)
                    elif w not in e["add"]: e["add"].append(w)
                else:
                    if w in e["add"]: e["add"].remove(w)
                    elif w not in e["remove"]: e["remove"].append(w)
            if t in cfg.topic_edits and not (e["add"] or e["remove"]):
                cfg.topic_edits.pop(t, None)
            set_topic_edits(cfg.topic_edits); self.save_config(); self.export()
            ed = cfg.topic_edits.get(t, {})
            ev("topic", t, topic=t, words=topic_words(t), added=ed.get("add", []), removed=ed.get("remove", []),
               on=t in cfg.filter_topics)
            return
        if sub in ("hide", "add", "show", "remove", "rm"):
            if not arg:
                raise KeyError(f"usage: /filter {sub} <topic or word>")
            import shlex
            try:
                items = shlex.split(arg)
            except ValueError:
                items = [arg.strip('"')]
            hide = sub in ("hide", "add")
            for it in items:
                low = it.lower()
                if low.startswith("@"):
                    h = low[1:]
                    if hide:
                        if h not in cfg.filtered_mentioners:
                            cfg.filtered_mentioners.append(h)
                        ev("align", f"filtering mentions from @{h}")
                    elif h in cfg.filtered_mentioners:
                        cfg.filtered_mentioners.remove(h); ev("align", f"showing mentions from @{h} again")
                    else:
                        raise KeyError(f"@{h} isn't a filtered mentioner (see /filter)")
                    continue
                if low in ALL_TOPICS:
                    cur = set(cfg.filter_topics)
                    cfg.filter_topics = [t for t in ALL_TOPICS if t in (cur | {low} if hide else cur - {low})]
                    ev("align", f"{'hiding' if hide else 'showing'} topic {low}"
                       + (f" ({', '.join(FILTER_TOPICS[low][:6])}…)" if hide and low in FILTER_TOPICS else ""))
                elif low in self.taxonomy:
                    cur = set(cfg.excluded_tags)
                    self.set_excluded(cur | {low} if hide else cur - {low})
                elif hide:
                    if low not in cfg.filter_words:
                        cfg.filter_words.append(low)
                    ev("align", f'hiding posts containing "{low}"')
                elif low in cfg.filter_words:
                    cfg.filter_words.remove(low); ev("align", f'showing posts containing "{low}" again')
                elif not hide and self._unfilter_subword(low):
                    pass
                else:
                    raise KeyError(f'"{it}" is not a filter topic or word (see /filter)')
            self.save_config(); self.export()
            hidden = sum(1 for p in self.found if p.get("source") != "mention" and self.filter_why(p))
            ev("info", f"{hidden} saved post(s) now hidden by the filter")
            return
        raise KeyError("usage: /filter [hide|show <topic or word>] [why <n>] [on|off]")

    def set_blocked(self, handles):
        self.cfg.blocked_authors = sorted({h.lower().lstrip("@") for h in handles}); self.save_config()
        q, added, dropped = self.effective_query()
        nh = sum(1 for p in self.found if self.hidden(p))
        self.log.event("align", f"block (local): {', '.join('@' + h for h in self.cfg.blocked_authors) or '(none)'} "
                       f"| {nh} found posts hidden" + (f" | {dropped} query terms dropped (length limit)" if dropped else ""))

    def _unfilter_subword(self, w):
        """Stop a broad topic from matching word w (e.g. 'fansly' in adult). True if any topic had it."""
        from .safety import ALL_TOPICS as AT, topic_words, set_topic_edits
        hit = [t for t in AT if w in topic_words(t)]
        for t in hit:
            e = self.cfg.topic_edits.setdefault(t, {"add": [], "remove": []})
            if w in e["add"]:
                e["add"].remove(w)
            else:
                e["remove"].append(w)
        if hit:
            set_topic_edits(self.cfg.topic_edits)
            self.log.event("align", f'"{w}" removed from topic {", ".join(hit)}; '
                           f'undo with /filter edit {hit[0]} +{w if " " not in w else repr(w)}')
        return bool(hit)

    def open_profile_to_block(self, handle):
        """b on a card: open x.com/<handle> so the user presses Block on X (the API can't), and block locally."""
        from .opener import open_url_async
        url = f"https://x.com/{handle}"
        if handle.lower() not in self.cfg.blocked_authors:
            self.handle(__import__("xbot.commands", fromlist=["parse"]).parse(f"/block @{handle}"))
        def done(method):
            if method:
                self.log.event("info", f"opened @{handle} [profile] via {method}: press ⋯ → Block there to finish blocking on X")
            else:
                self.log.event("warn", f"no browser opener worked; open {url} and press Block there")
        (self.opener or open_url_async)(url, done)
        return url

    def open_profile(self, n):
        from .opener import open_url_async
        p = self.found_post(n); h = p.get("username")
        if not h:
            self.log.event("info", f"#{n}: author handle unknown"); return None
        url = f"https://x.com/{h}"
        (self.opener or open_url_async)(url, lambda m: self.log.event(
            "info", f"opened @{h} [profile] via {m}" if m else f"no browser opener worked; open manually: {url}"))
        return url

    def is_video(self, n):
        ms = self.found_post(n).get("media") or []
        return bool(ms) and ms[0].get("type") in ("video", "animated_gif") and bool(ms[0].get("url"))

    def video_url(self, n, forbidden=None):
        """Stream URL of found post #n's video; on a 403 (expired URL) the post is refetched once."""
        from .video import url_forbidden
        p = self.found_post(n)
        if not self.is_video(n):
            return None
        url = p["media"][0]["url"]
        chk = forbidden or getattr(self, "video_forbidden", None) or url_forbidden
        get = getattr(self.rx, "get_post", None)
        if get and chk(url):
            try:
                fresh = get(p["id"]); self._charge(COST_READ, self.reads_live())
            except XError as e:
                self._xerr(e); return url
            if fresh and fresh.get("media"):
                p["media"] = fresh["media"]; url = fresh["media"][0].get("url") or url
                self.log.event("info", f"#{n} video URL expired: refetched the post")
        return url

    def media_items(self, n, forbidden=None):
        """All media of found post #n (photos, videos, GIFs) for the mpv viewer; an expired (403) video URL
        refetches the post once."""
        p = self.found_post(n)
        vids = [m for m in p.get("media") or [] if m.get("type") in ("video", "animated_gif") and m.get("url")]
        if vids:
            url = vids[0]["url"]
            chk = forbidden or getattr(self, "video_forbidden", None)
            if chk is None:
                from .video import url_forbidden as chk
            get = getattr(self.rx, "get_post", None)
            if get and chk(url):
                try:
                    fresh = get(p["id"]); self._charge(COST_READ, self.reads_live())
                except XError as e:
                    self._xerr(e); return p.get("media") or []
                if fresh and fresh.get("media"):
                    p["media"] = fresh["media"]
                    self.log.event("info", f"#{n} video URL expired: refetched the post")
        return self.found_post(n).get("media") or []

    def set_filtered_mentioners(self, handles):
        old = set(self.cfg.filtered_mentioners)
        self.cfg.filtered_mentioners = list(dict.fromkeys(h.lower().lstrip("@") for h in handles))
        self.save_config()
        new = set(self.cfg.filtered_mentioners)
        self.log.event("align", "filtered mentioners: " + (", ".join("@" + h for h in self.cfg.filtered_mentioners) or "(none)")
                       + (f" · added {', '.join('@' + h for h in sorted(new - old))}" if new - old else "")
                       + (f" · removed {', '.join('@' + h for h in sorted(old - new))}" if old - new else ""))

    def filter_mentioner_post(self, n):
        """q on a mention's post card: hide this person's mentions from now on and drop their pending drafts."""
        p = self.found_post(n)
        who = (p.get("username") or "").lower()
        if p.get("source") != "mention" or not who:
            raise KeyError("q filters a mentioner: open a mention's card")
        return self._filter_who(who)

    def filter_mentioner(self, draft_id):
        """Filter the author of a mention reply draft (same effect as q on the mention's card)."""
        d = self.queue.get(draft_id)
        p = next((p for p in self.found if p["id"] == d.in_reply_to), {})
        who = (p.get("username") or "").lower()
        if d.source != "mention" or not who:
            raise KeyError("pick a mention reply")
        return self._filter_who(who)

    def _filter_who(self, who):
        if who not in self.cfg.filtered_mentioners:
            self.cfg.filtered_mentioners.append(who)
        ids = {x["id"] for x in self.found if (x.get("username") or "").lower() == who}
        dropped = 0
        for x in self.queue.pending():
            if x.source == "mention" and x.in_reply_to in ids:
                self.queue.reject(x.id); dropped += 1
        self.save_config(); self.export()
        self.log.event("align", f"filtering mentions from @{who}; dropped {dropped} draft(s). Undo: /filter show @{who} · edit the list: m or /mentioners")
        return who

    def set_topic_words(self, t, words):
        """Save topic t's keyword list as edits against its built-in list (used by the picker screen)."""
        from .safety import BASE_WORDS, set_topic_edits
        base = BASE_WORDS.get(t, [])
        words = [w.strip().lower() for w in words if w.strip()]
        add = [w for w in dict.fromkeys(words) if w not in base]
        rm = [w for w in base if w not in words]
        if add or rm:
            self.cfg.topic_edits[t] = {"add": add, "remove": rm}
        else:
            self.cfg.topic_edits.pop(t, None)
        set_topic_edits(self.cfg.topic_edits); self.save_config(); self.export()
        self.log.event("info", f"topic {t}: {len(words)} words" + (f", +{len(add)} added" if add else "")
                       + (f", -{len(rm)} removed" if rm else ""))

    def set_filter_topics(self, on):
        from .safety import ALL_TOPICS as AT
        self.cfg.filter_topics = [t for t in AT if t in set(on)]; self.save_config(); self.export()
        self.log.event("info", "broad topics hidden: " + (", ".join(self.cfg.filter_topics) or "(none)"))

    def set_excluded(self, tags):
        self.cfg.excluded_tags = sorted(set(tags)); self.save_config()
        q, added, dropped = self.effective_query()
        nh = sum(1 for p in self.found if self.hidden(p))
        self.log.event("align", f"excluded tags: {', '.join(self.cfg.excluded_tags) or '(none)'} "
                       f"| {nh} found posts hidden | query +{added} -terms" + (f", {dropped} dropped (length limit)" if dropped else ""))

    def draft_for_post(self, n):
        """Grok draft for found post #n (None if Grok off/failed). Blocking: call from a worker."""
        p = self.found_post(n)
        if self.state.prefill.get(str(p["id"])):
            return self.state.prefill[str(p["id"])]  # stored draft: no API call
        who = p.get("username") or p.get("author_id", "?")
        labels = ", ".join(label_ids(p)) or "none"
        return self._draft(manual=True, user_prompt=f"Post by @{who} ({p.get('name') or who}):\n\n{p['text']}\n\nTopics/labels: {labels}\n\n"
                           "Write a relevant, specific, non-spammy reply that adds value. No self-promotion, no links, "
                           "no hashtags. Output only the reply text.")

    def queue_reply_to_found(self, n, text, grok_text=None):
        p = self.found_post(n)
        self.learn_style(p["id"], p.get("text", ""), grok_text, text)
        self.drop_prefill(p["id"])
        return self._enqueue("reply", text, in_reply_to=p["id"], source="manual",
                             conversation_id=p.get("conversation_id") or p["id"])

    def browser_reply_to_found(self, n, text, grok_text=None):
        """Ctrl+B in the reply editor: the reply was opened in the browser (X web intent). Record it like an
        approved browser reply: a queue.json draft with status "sent", the post marked replied, its thread in
        state.replied_threads (so it isn't drafted again)."""
        p = self.found_post(n)
        self.learn_style(p["id"], p.get("text", ""), grok_text, text)
        self.drop_prefill(p["id"])
        conv = p.get("conversation_id") or p["id"]
        d = self._enqueue("reply", text, in_reply_to=p["id"], source="manual", conversation_id=conv)
        self.queue.set_status(d.id, "sent")
        p["replied"] = True
        if conv not in self.state.replied_threads:
            self.state.replied_threads.append(conv)
        self.remove_found(p["id"])  # replied posts leave found.json for good (queue + replied_threads remember)
        self.state.save()
        self.export()
        self.log.event("sent", f"#{d.id} reply to #{n} posted via browser (saved as sent, post removed)")
        return d

    def send_reply_to_found(self, n, text, grok_text=None):
        """Send now via the normal path (dry/live, cap). Marks replied on success."""
        p = self.found_post(n)
        self.learn_style(p["id"], p.get("text", ""), grok_text, text)
        tid = self.send("reply", text, in_reply_to=p["id"], summoned=p.get("source") == "mention")
        if tid:
            p["replied"] = True
            self.state.replied_threads.append(p.get("conversation_id") or p["id"])
            self.remove_found(p["id"]); self.state.save()
            self.export()
        elif p.get("source") != "mention" and not self.cfg.dry_run:
            self.log.event("warn", "note: X self-serve API only allows replies to posts that summoned you "
                           f"(mention/quote); use /open {n} to reply by hand")
        return tid

    def remove_found(self, pid):
        """Drop a post from the found list (renumbers the rest), its other pending drafts and its F5 cursor entry."""
        pid = str(pid)
        self.found = [p for p in self.found if str(p["id"]) != pid]
        for d in self.queue.pending():
            if d.in_reply_to and str(d.in_reply_to) == pid:
                self.queue.set_status(d.id, "rejected")
        self.state.feed_shown = [i for i in self.state.feed_shown if str(i) != pid]

    def purge_replied(self):
        """One-time cleanup: remove every found post already marked replied (like remove_found). Returns count."""
        ids = [str(p["id"]) for p in self.found if p.get("replied")]
        for pid in ids:
            self.remove_found(pid)
        if ids:
            self.state.save(); self.export()
        return len(ids)

    def found_post(self, n):
        if not 1 <= n <= len(self.found):
            raise KeyError(f"no found post #{n}")
        return self.found[n - 1]

    def resolve_id(self, ref):
        if ref.startswith("#"):
            n = int(ref[1:])
            if not 1 <= n <= len(self.found):
                raise KeyError(f"no found post {ref}")
            return self.found[n - 1]["id"]
        return ref

    def rate_limited(self, manual=False):
        """Seconds until Grok may be called (xAI 429 back-off; auto calls also wait for own pacing)."""
        until = self.llm_backoff_until if manual else max(self.llm_backoff_until, self.auto_wait_until)
        return max(0, int(until - self._clock() + 0.999))

    def _draft(self, user_prompt, manual=False, raw=False):
        self.last_draft_error = None
        if self.llm is None:
            return None
        if self.check_spend_limit():
            return None  # never send an xAI request at/over the limit
        left = self.rate_limited(manual=True)
        if left:
            self.last_draft_error = f"xAI rate limit: retrying in {left}s"
            return None
        if manual and not self._pace_ok(True):
            # g never gets refused for pacing: wait (in the worker thread) for the next free slot
            wait = self.manual_wait()
            if wait > 0:
                self.last_draft_error = None
                (getattr(self, "sleep", None) or __import__("time").sleep)(wait)
            if not self._pace_ok(True):
                self.last_draft_error = f"key limit {self.cfg.llm_rpm}/min reached, try again"
                return None
        elif not manual and not self._pace_ok(False):
            left = self.rate_limited(manual)
            self.last_draft_error = (f"key limit {self.cfg.llm_rpm}/min reached: try again in {left}s" if manual
                                     else f"auto drafting paced at {self.cfg.llm_auto_rpm}/min: next in {left}s")
            return None
        try:
            self.llm.last_cost_usd = 0.0
            try:
                t = self.llm.complete(self.system_prompt(), user_prompt).strip().strip('"')
            finally:
                self.state.add_grok_spend(float(getattr(self.llm, "last_cost_usd", 0) or 0))
                self.check_spend_limit()
            self.llm_backoff_until = 0.0  # success: any stale 429 back-off is over
            return t if raw else t[: self.cfg.max_chars]
        except LLMFatal as e:
            self.paused = True
            self.last_draft_error = "xAI auth/credit error, bot paused"
            self.log.event("error", f"{e} -- bot PAUSED. Fix key/credits then /resume.")
        except LLMRateLimited as e:
            self.llm_backoff_until = self._clock() + e.retry_after
            self.last_draft_error = f"xAI rate limit: retrying in {int(e.retry_after)}s"
            self.log.event("warn", f"xAI 429: key limit is lower than llm_rpm={self._rpm()} (auto {self.auto_limit()}/min); "
                                   f"raise it at console.x.ai or run xbot config llm_rpm N. Retrying in {int(e.retry_after)}s")
        except LLMTimeout as e:
            n = getattr(self, "_draft_n", 1) or 1
            msg = f"Grok timed out after {int(e.seconds)}s drafting {n} post{'s' if n != 1 else ''}; will retry next refresh"
            self.last_draft_error = msg
            self.log.event("warn", msg)
        except LLMError as e:
            self.last_draft_error = clip(str(e), 120)
            self.log.event("warn", str(e))
        return None

    def auto_limit(self):
        """Effective auto-drafting calls/min (0 = unlimited). Keeps >= 1 slot of llm_rpm for manual g drafts."""
        rpm, auto = self._rpm(), max(0, int(self.cfg.llm_auto_rpm or 0))
        if rpm >= 2:
            return min(auto, rpm - 1) if auto > 0 else rpm - 1
        if rpm == 1:
            return 1  # one slot: auto ~1/min, a manual g call in the window makes auto wait (g first)
        return auto  # pacing off: auto limit alone (0 = unlimited)

    def _rpm(self):
        """llm_rpm: >= 1, or 0 = pacing off (negatives treated as 0)."""
        return max(0, int(self.cfg.llm_rpm or 0))

    def manual_wait(self):
        """Seconds (float, > 0 only when really full) until the key window has a free slot."""
        rpm = self._rpm()
        now = self._clock()
        calls = [t for t, _ in self._llm_calls if now - t < 60]
        if not rpm or len(calls) < rpm:
            return 0.0
        return max(0.0, calls[len(calls) - rpm] + 60 - now) + 0.01

    def _pace_ok(self, manual=False):
        """Sliding 60 s window: total calls <= llm_rpm, auto calls <= auto_limit() (llm_auto_rpm),
        so auto drafting never uses the slot kept for manual g drafts."""
        rpm, lim = self._rpm(), self.auto_limit()
        now = self._clock()
        self._llm_calls = [(t, m) for t, m in self._llm_calls if now - t < 60]
        autos = [t for t, m in self._llm_calls if not m]
        if manual:
            if rpm and len(self._llm_calls) >= rpm:
                return False
        else:
            if lim and len(autos) >= lim:
                self.auto_wait_until = autos[0] + 60
            elif rpm and len(self._llm_calls) >= rpm:
                self.auto_wait_until = self._llm_calls[0][0] + 60
            else:
                self.auto_wait_until = 0.0
            if self.auto_wait_until:
                if not self._pace_logged:
                    self._pace_logged = True
                    self.log.event("info", f"auto drafting paced at {lim}/min (llm_auto_rpm; key limit llm_rpm={rpm}, "
                                           "the rest is kept for g): remaining drafts fill in gradually")
                return False
        self._llm_calls.append((now, manual))
        return True

    def retry_due(self):
        """True once a 429 back-off has ended and the catalog still has posts to draft."""
        return bool(self.llm_backoff_until or self.auto_wait_until) and not self.rate_limited() and self.grok_on and self.catalog_size() > 0

    def mention_pending(self):
        return [d for d in self.queue.pending() if d.source == "mention"]

    def mentions_waiting(self):
        """Mentions in the feed that never got a draft (oldest first); drafted as mention slots free up."""
        done = {str(d.in_reply_to) for d in self.queue.items if d.in_reply_to}
        fm = {h.lower() for h in self.cfg.filtered_mentioners}
        return [p for p in self.found if p.get("source") == "mention" and str(p["id"]) not in done
                and not p.get("replied") and not p.get("user_hidden") and (p.get("username") or "").lower() not in fm]

    def _draft_mentions(self):
        return self.schedule_drafts(only="mention")

    def queue_full(self):
        full = self.cfg.max_pending > 0 and len(self.queue.pending_capped()) >= self.cfg.max_pending
        if full and not self._full_logged:
            self.log.event("warn", f"suggested-reply queue full ({self.cfg.max_pending}); mentions still get drafted, "
                                   f"suggestions pause until you approve/reject")
        self._full_logged = full
        return full

    def _enqueue(self, kind, text, **kw):
        if kw.get("source") in ("mention", "search"):
            kw.setdefault("grok_text", text)
        d = self.queue.add(kind, text, **kw)
        tgt = f" ->{d.in_reply_to}" if d.in_reply_to else ""
        self.log.event("draft", f"#{d.id} {d.source} {kind}{tgt}: {text}")
        if URL_RE.search(text):
            self.log.event("warn", f"#{d.id} contains a URL: costs ${COST_POST_URL:.2f} instead of ${COST_POST:.3f} if sent")
        return d

    def _reply_budget_ok(self):
        if self.state.reply_sends_last_hour() >= self.cfg.max_replies_per_hour:
            return False
        return True

    def tick(self, force_search=False):
        """One poll cycle: mentions + (search if due or forced). Returns number of drafts created."""
        if self.paused or self.stopped:
            return 0
        self.ticks += 1
        self.last_check = __import__("time").time()
        made = 0
        # mentions (summoned: replies allowed)
        try:
            live = self.reads_live()
            ms = self.rx.mentions(self.since_id)
            self._charge(len(ms) * COST_OWNED_READ, live)
        except XError as e:
            self._xerr(e); ms = []
        ms = sorted(ms, key=lambda m: int(m["id"]))
        if ms:
            self.since_id = ms[-1]["id"]
        new = [m for m in ms if m["id"] not in self.state.seen]
        self.prefetch_authors(new)
        fm = {h.lower() for h in self.cfg.filtered_mentioners}
        shown = [m for m in new if (m.get("username") or "").lower() not in fm]
        nfm = len(new) - len(shown)
        self.log.event("section", f"Mentions ({len(shown)} new)" + (f" · {nfm} from filtered mentioners" if nfm else ""))
        for m in new:
            self.state.seen.append(m["id"])
        for m in shown:
            self._remember(m, "mention")
        self.state.save()
        # tech search
        if self.cfg.search_enabled and (force_search or (self.cfg.search_every_n_ticks
                and (self.ticks - 1) % self.cfg.search_every_n_ticks == 0)):
            made += self._search()
            if self.paused:
                return made
        if self.grok_on:  # one scheduler for both queues (emptiest first, then shared prefill pool)
            made += self.schedule_drafts()
            if self.paused:
                return made
        # original posts
        if self.grok_on and self.cfg.post_every_n_ticks and self.ticks % self.cfg.post_every_n_ticks == 0 and not self.queue_full():
            topic = self.rng.choice(self.cfg.topics) if self.cfg.topics else "anything"
            t = self._draft(f"Write an original post about: {topic}")
            if t:
                self._enqueue("post", t, context=topic)
                made += 1
        return made

    def _note_oldest(self, pid):
        if self.search_oldest_id is None or int(pid) < int(self.search_oldest_id):
            self.search_oldest_id = str(pid)

    def _search_usable(self, p, me):
        """Would this fetched post become a suggestion (unseen, not replied/self, not filtered)?"""
        if p["id"] in self.state.seen or (p.get("conversation_id") or p["id"]) in self.state.replied_threads:
            return False
        if me and p.get("author_id") == me:
            return False
        if self.cfg.auto_filter and self.filter_why(p):
            return False
        if self.cfg.excluded_tags:
            tmp = {"tags": tag_post(p, self.taxonomy), "xlabels": x_labels(p)}
            if set(label_ids(tmp)) & set(self.cfg.excluded_tags):
                return False
        return (p.get("username") or "").lower() not in self.cfg.blocked_authors

    def _search(self):
        if self.cap_hit():
            self.log.event("info", "daily cap reached; skipping search")
            return 0
        try:
            live = self.reads_live()
            query = self.effective_query()[0]
            posts = self.rx.search_recent(query, self.cfg.search_max_results, self.search_since_id)
            self._charge(len(posts) * COST_READ, live)
        except XError as e:
            self._xerr(e); return 0
        me = None
        try:
            me = self.rx.me(); self._cache_me(self.rx)
        except XError:
            pass
        posts = sorted(posts, key=lambda p: int(p["id"]))
        if posts:
            self.search_since_id = posts[-1]["id"]
            self._note_oldest(posts[0]["id"])
        older_ids = set()
        if self.cfg.search_backfill and self.search_oldest_id is not None:
            usable = sum(1 for p in posts if self._search_usable(p, me))
            if usable < self.cfg.search_max_results:
                if self.cap_hit() or (self.grok_on and not self._reply_budget_ok()):
                    pass  # budget/cap blocks the extra read
                else:
                    try:
                        old = self.rx.search_recent(query, self.cfg.search_max_results, None,
                                                    until_id=self.search_oldest_id)
                        self._charge(len(old) * COST_READ, live)
                    except XError as e:
                        self._xerr(e); old = []
                    have = {p["id"] for p in posts}
                    old = [p for p in old if p["id"] not in have]
                    if old:
                        self._note_oldest(min(old, key=lambda p: int(p["id"]))["id"])
                        older_ids = {p["id"] for p in old}
                        posts = sorted(posts + old, key=lambda p: int(p["id"]))
                    else:
                        self.log.event("info", "no older posts left (search covers last 7 days)")
        posts = [p for p in posts if not (p["id"] in self.state.seen
                 or (p.get("conversation_id") or p["id"]) in self.state.replied_threads
                 or (me and p.get("author_id") == me))]
        hidden = 0
        import time as _t
        self._batch = max([f.get("batch", 0) for f in self.filtered] + [int(_t.time())]) + 0
        if self._batch <= max([f.get("batch", 0) for f in self.filtered] + [0]):
            self._batch += 1
        if self.cfg.auto_filter:
            keep = []
            for p in posts:
                why = self.filter_why(p)
                if why:
                    self.state.seen.append(p["id"]); hidden += 1
                    self._keep_filtered(p, filter_detail(p, self.cfg.filter_topics, self.cfg.filter_words) or why)
                else:
                    keep.append(p)
            posts = keep
        if self.cfg.excluded_tags:
            keep = []
            for p in posts:
                tmp = {"tags": tag_post(p, self.taxonomy), "xlabels": x_labels(p)}
                bad = sorted(set(label_ids(tmp)) & set(self.cfg.excluded_tags))
                if bad:
                    self.state.seen.append(p["id"]); hidden += 1
                    self._keep_filtered(p, [f"tag {t}" for t in bad])
                else:
                    keep.append(p)
            posts = keep
        self.prefetch_authors(posts)
        if self.cfg.blocked_authors:
            keep = []
            for p in posts:
                if (p.get("username") or "").lower() in self.cfg.blocked_authors:
                    self.state.seen.append(p["id"])
                else:
                    keep.append(p)
            posts = keep
        n_older = sum(1 for p in posts if p["id"] in older_ids)
        self.log.event("section", f"Suggested replies ({len(posts)})" + (f" · {n_older} older" if n_older else "")
                       + (f" · {hidden} hidden by filter (/hidden)" if hidden else ""),
                       raw=len(posts))
        infeed = {f["id"] for f in self.found}
        for p in posts:  # every fetched post goes to the feed/catalog, drafted or not
            self.state.seen.append(p["id"])
            if p["id"] not in infeed:
                self._remember(p, "search"); infeed.add(p["id"])
        self.state.save()
        return 0  # drafting happens in schedule_drafts() after the fetch

    def search_catalog(self):
        """Search posts in the feed still waiting for a draft (oldest first, like the fetch order): no draft yet, not SKIPped/replied/hidden."""
        done = {str(d.in_reply_to) for d in self.queue.items if d.in_reply_to}
        out = [p for p in self.found if p.get("source") == "search" and str(p["id"]) not in done
               and p["id"] not in self._skipped and not p.get("replied") and not p.get("user_hidden")
               and (p.get("conversation_id") or p["id"]) not in self.state.replied_threads
               and (p.get("username") or "").lower() not in self.cfg.blocked_authors
               and not (self.cfg.auto_filter and self.filter_why(p))]
        return sorted(out, key=lambda p: int(p["id"]))

    SKIP_RULE = (" Reply with exactly SKIP only if the post is clearly spam, a scam, sexual, or hateful;"
                 " otherwise always write a reply.")

    def _batch_prompt(self, chunk):
        items = "\n\n".join(f"[{p['id']}] @{p.get('username') or p.get('author_id', '?')}: {p['text']}" for p in chunk)
        skip = self.SKIP_RULE if self.cfg.allow_skip else ""
        return (f"Write one reply for EACH post below. Each reply: relevant, specific, adds value, under "
                f"{self.cfg.max_chars} characters, no self-promotion, no links, no hashtags.{skip}\n"
                'Answer with JSON only: [{"id": "<post id>", "reply": "<text or SKIP>"}, ...]\n\n' + items)

    @staticmethod
    def parse_batch(text, ids):
        """JSON list of {id, reply} -> {id: reply}; tolerant of code fences / prose around it. None if unusable."""
        import json
        if not text:
            return None
        a, b = text.find("["), text.rfind("]")
        if a < 0 or b <= a:
            return None
        try:
            data = json.loads(text[a:b + 1])
        except ValueError:
            return None
        out = {}
        for d in data if isinstance(data, list) else []:
            if isinstance(d, dict) and str(d.get("id")) in ids and isinstance(d.get("reply"), str) and d["reply"].strip():
                out[str(d["id"])] = d["reply"].strip().strip('"')
        return out or None

    def _search_slots(self):
        mp = self.cfg.max_pending
        return (mp - len(self.queue.pending_capped())) if mp > 0 else 10**6

    def _accept(self, p, t, kind="search"):
        who = p.get("username") or p.get("author_id", "?")
        if kind == "mention" and t.strip().upper().rstrip(".") != "SKIP":
            self._enqueue("reply", t[: self.cfg.max_chars], in_reply_to=p["id"], context=p["text"], source="mention",
                          conversation_id=p.get("conversation_id"))
            return 1
        if t.strip().upper().rstrip(".") == "SKIP":
            self._skipped.add(p["id"])
            self.log.event("skip", f"@{who}: {clip(p['text'], 80)}")
            return 0
        self._enqueue("reply", t[: self.cfg.max_chars], in_reply_to=p["id"], context=f"@{who}: {p['text']}",
                      source="search", conversation_id=p.get("conversation_id") or p["id"])
        return 1

    # ---- prefill pool: drafts for upcoming feed posts, promoted into free slots without an API call ----
    def drop_prefill(self, pid):
        if self.state.prefill.pop(str(pid), None) is not None:
            self.state.save()

    def prune_prefill(self):
        """Drop stored drafts of posts now hidden, filtered, blocked, replied or SKIPped."""
        ok = {str(p["id"]) for p in self.search_catalog()} | {str(p["id"]) for p in self.mentions_waiting()}
        known = {str(p["id"]) for p in self.found}
        bad = [k for k in self.state.prefill if k in known and k not in ok]
        for k in bad:
            self.state.prefill.pop(k)
        if bad:
            self.state.save()

    # ---- drafting scheduler: two queues (mention / search) + one shared prefill pool ----
    KINDS = ("mention", "search")

    def _cands(self, kind):
        return sorted(self.mentions_waiting(), key=lambda p: int(p["id"])) if kind == "mention" else self.search_catalog()

    def _free(self, kind):
        if kind == "mention":
            cap = self.cfg.max_mention_drafts
            return cap - len(self.mention_pending()) if cap > 0 else 10**6
        return 0 if self.queue_full() else max(0, self._search_slots())

    def _ratio(self, kind):
        cap = self.cfg.max_mention_drafts if kind == "mention" else self.cfg.max_pending
        n = len(self.mention_pending()) if kind == "mention" else len(self.queue.pending_capped())
        return n / cap if cap > 0 else 0.0

    def _batch_n(self):
        try:
            return max(1, int(self.cfg.draft_batch or 1))
        except (TypeError, ValueError):  # hand-edited non-number: one post per request
            return 1

    def _pool_count(self, kind):
        ids = {str(p["id"]) for p in self._cands(kind)}
        return sum(1 for k in self.state.prefill if k in ids)

    def _kind_room(self, kind):
        """Prefill room for one kind: the pool is shared fairly (half each while both have posts waiting)."""
        if self._batch_n() == 1:
            return 0  # draft_batch 1 = one post per request, no prefill
        room = self._prefill_room()
        other = "search" if kind == "mention" else "mention"
        if self._unprefilled(self._cands(other)):
            share = int(self.cfg.prefill_max) - int(self.cfg.prefill_max) // 2 if kind == "mention" else int(self.cfg.prefill_max) // 2
            room = min(room, max(0, share - self._pool_count(kind)))
        return room

    def _pick(self, kinds, key):
        """Lowest key wins; ties alternate between the kinds."""
        if not kinds:
            return None
        best = min(key(k) for k in kinds)
        tied = [k for k in kinds if key(k) == best]
        if len(tied) > 1:
            k = tied[0] if self._last_kind != tied[0] else tied[1]
        else:
            k = tied[0]
        return k

    def next_job(self, only=None):
        """(kind, posts, phase) for the next Grok request, or None when everything is full (no request)."""
        kinds = [k for k in self.KINDS if only in (None, k)]
        n = self._batch_n()
        fill = [k for k in kinds if self._free(k) > 0 and self._unprefilled(self._cands(k))]
        k = self._pick(fill, self._ratio)
        if k:
            todo = self._unprefilled(self._cands(k))
            size = min(n, self._free(k) + self._kind_room(k))
            return k, todo[:max(1, size)], "fill"
        # prefill only once both queues are full (or have nothing left to fill)
        pre = [k for k in kinds if self._kind_room(k) > 0 and self._unprefilled(self._cands(k))]
        k = self._pick(pre, self._pool_count)
        if k:
            return k, self._unprefilled(self._cands(k))[:min(n, self._kind_room(k))], "prefill"
        return None

    def promote_prefill(self, posts=None):
        made = 0
        for kind in self.KINDS:
            for p in self._cands(kind) if posts is None else [q for q in posts if (q.get("source") == "mention") == (kind == "mention")]:
                if self._free(kind) <= 0:
                    break
                t = self.state.prefill.pop(str(p["id"]), None)
                if t:
                    made += self._accept(p, t, kind)
        if made:
            self.state.save()
        return made

    def _prefill_room(self):
        return max(0, int(self.cfg.prefill_max) - len(self.state.prefill))

    def _unprefilled(self, posts):
        return [p for p in posts if str(p["id"]) not in self.state.prefill]

    def search_needs_grok(self, posts=None):
        return self.next_job(only="search") is not None

    def _mention_prompt(self, chunk):
        if len(chunk) == 1 and self._batch_n() == 1:
            return f"Reply to this post that mentions us:\n\n{chunk[0]['text']}"
        return "These posts mention us. " + self._batch_prompt(chunk)

    def _single_prompt(self, p):
        who = p.get("username") or p.get("author_id", "?")
        skip = self.SKIP_RULE if self.cfg.allow_skip else ""
        return (f"Post by @{who}:\n\n{p['text']}\n\nWrite a relevant, specific, non-spammy reply that adds "
                f"value. No self-promotion, no links, no hashtags.{skip}")

    def schedule_drafts(self, only=None, max_requests=50):
        """Grok requests one at a time, each to the emptiest queue (ties alternate); leftovers go to the shared
        prefill pool, which is only filled on its own once both queues are full. No request when all is full."""
        if getattr(self, "drafting_hold", False):
            return 0  # bare /clear: paused until F5
        made = self.promote_prefill()
        waiting = len(self.mentions_waiting())
        for _ in range(max_requests):
            job = self.next_job(only)
            if job is None:
                break
            kind, chunk, phase = job
            self._last_kind = kind
            single = self._batch_n() == 1
            prompt = (self._mention_prompt(chunk) if kind == "mention"
                      else self._single_prompt(chunk[0]) if single else self._batch_prompt(chunk))
            self._draft_n = len(chunk)
            try:
                raw = self._draft(prompt, raw=True)
            finally:
                self._draft_n = 1
            if self.paused or (raw is None and self.rate_limited()):
                break
            if raw is None:
                break
            if single:
                got = {str(chunk[0]["id"]): raw.strip().strip('"')}
            else:
                got = self.parse_batch(raw, {str(p["id"]) for p in chunk})
                if got is None:
                    if raw:
                        self.log.event("warn", "batch draft not JSON; drafting one post per request")
                    if len(chunk) == 1:
                        got = {str(chunk[0]["id"]): raw.strip().strip('"')}
                    else:
                        made += self._fallback_single(kind, chunk)
                        if self.paused or self.rate_limited():
                            break
                        continue
            for p in chunk:
                t = got.get(str(p["id"]))
                if not t:
                    self._skipped.add(p["id"]); continue  # unanswered: don't re-ask forever
                if t.strip().upper().rstrip(".") == "SKIP" or self._free(kind) > 0:
                    made += self._accept(p, t, kind)
                else:
                    self.state.prefill[str(p["id"])] = t[: self.cfg.max_chars]
            self.state.save()
            if self.rate_limited():
                break
        left = len(self.mentions_waiting())
        cap = self.cfg.max_mention_drafts
        if left and cap > 0 and self._free("mention") <= 0 and left != waiting:
            self.log.event("info", f"{left} mention(s) waiting: mention drafts at {cap}/{cap}; "
                                   f"approve/reject one and the next is drafted")
        return made

    def _fallback_single(self, kind, chunk):
        made = 0
        for p in chunk[:max(1, min(len(chunk), self._free(kind)))]:
            prompt = f"Reply to this post that mentions us:\n\n{p['text']}" if kind == "mention" else self._single_prompt(p)
            t = self._draft(prompt)
            if self.paused or self.rate_limited():
                break
            if t:
                made += self._accept(p, t, kind)
        return made

    def _draft_search(self, posts):
        return self.schedule_drafts(only="search")

    def _draft_search_single(self, posts):
        made = 0
        for p in posts:
            conv = p.get("conversation_id") or p["id"]
            if self.queue_full():
                break
            who = p.get("username") or p.get("author_id", "?")
            skip = self.SKIP_RULE if self.cfg.allow_skip else ""
            t = self._draft(f"Post by @{who}:\n\n{p['text']}\n\nWrite a relevant, specific, non-spammy reply that adds "
                            f"value. No self-promotion, no links, no hashtags.{skip}")
            if self.paused or self.rate_limited():
                break
            if not t:
                continue
            if t.strip().upper().rstrip(".") == "SKIP":
                self._skipped.add(p["id"])
                self.log.event("skip", f"@{who}: {clip(p['text'], 80)}")
                continue
            self._enqueue("reply", t, in_reply_to=p["id"], context=f"@{who}: {p['text']}", source="search",
                          conversation_id=conv)
            made += 1
        self.state.save()
        return made

    def catalog_size(self):
        """Feed posts/mentions still waiting for a draft (not replied, rejected, drafted or hidden)."""
        return len(self.mentions_waiting()) + len(self.search_catalog())

    # ---- queue positions (shown 1..n per section; real ids stay internal) ----
    def queue_groups(self):
        ps = self.queue.pending()
        return [d for d in ps if d.source == "mention"], [d for d in ps if d.source != "mention"]

    def draft_pos(self, did):
        """('m'|'', 1-based position) of a pending draft, or None."""
        ms, ss = self.queue_groups()
        for pre, grp in (("m", ms), ("", ss)):
            for i, d in enumerate(grp, 1):
                if d.id == did:
                    return pre, i
        return None

    def draft_label(self, did):
        p = self.draft_pos(did)
        if not p:
            return f"draft {did}"
        return f"mention {p[1]}" if p[0] else f"suggested {p[1]}"

    def resolve_draft(self, ref):
        """'2' -> Suggested replies #2, 'm2' -> Mentions #2, '@15' -> real id 15 (internal, keys)."""
        ref = str(ref).strip().lower()
        if ref.startswith("@"):
            return int(ref[1:])
        ms, ss = self.queue_groups()
        grp, i = (ms, int(ref[1:])) if ref.startswith("m") else (ss, int(ref))
        if not 1 <= i <= len(grp):
            where = "Mentions" if ref.startswith("m") else "Suggested replies"
            raise KeyError(f"no draft {ref} in {where} ({len(grp)} shown)")
        return grp[i - 1].id

    def reject_draft(self, did):
        """Reject + hide its source post (listed in /hidden, never drafted again; mentions: only that post,
        the author is not muted/blocked). Instant: no network; new drafts come from the background worker."""
        d = self.queue.get(did); lbl = self.draft_label(did)
        self.queue.reject(did)
        self.log.event("reject", lbl)
        n = next((i for i, p in enumerate(self.found, 1) if str(p["id"]) == str(d.in_reply_to)), None)
        if n:
            self.hide_post(n, forever=False, why=["rejected draft"])
        self.refill_quick()

    def refill_quick(self):
        """UI-thread safe refill: only promote stored prefill drafts (no Grok/X request, no lock wait)."""
        if not self.grok_on or self.paused or self.stopped:
            return 0
        try:
            self.prune_prefill()
            return self.promote_prefill()
        except Exception as e:
            self.log.event("warn", f"refill failed: {type(e).__name__}"); return 0

    def refill_from_catalog(self):
        """Draw Grok drafts from the catalog (waiting mentions + search posts in the feed) into free slots. No network."""
        if not self.grok_on or self.paused or self.stopped:
            return 0
        self.prune_prefill()  # filters may have changed
        promoted = self.promote_prefill()  # stored drafts first: instant, no API call
        if self.rate_limited():
            return promoted
        if not self._draft_lock.acquire(blocking=False):
            return promoted  # another drafting pass is running (F5 vs background worker)
        try:
            self.llm_backoff_until = 0.0
            return self.schedule_drafts() + promoted
        finally:
            self._draft_lock.release()

    def free_slots(self):
        mc, mp = self.cfg.max_mention_drafts, self.cfg.max_pending
        fm = (mc - len(self.mention_pending())) if mc > 0 else (1 if self.mentions_waiting() else 0)
        fs = (mp - len(self.queue.pending_capped())) if mp > 0 else 1
        return (max(0, fm) if self.mentions_waiting() else 0) + (max(0, fs) if self.search_catalog() else 0)

    def wants_drafting(self):
        """Background worker: something to draft or promote. False when everything is full (no Grok request)."""
        if not (self.grok_on and not self.paused and not self.stopped) or getattr(self, "drafting_hold", False):
            return False
        for k in self.KINDS:
            if self._free(k) > 0 and any(str(p["id"]) in self.state.prefill for p in self._cands(k)):
                return True
        return self.next_job() is not None

    def drafting_status(self):
        pre = f"prefilled {len(self.state.prefill)}" if self.state.prefill else ""
        if getattr(self, "drafting_hold", False):
            return " · ".join(x for x in ("drafting paused (F5 resumes)", pre) if x)
        if not self.grok_on:
            return pre
        if not self.wants_drafting():
            st = "drafts full" if not self.paused else ""
        else:
            left = self.rate_limited()
            st = f"drafting… next in {left}s" if left else "drafting…"
        return " · ".join(x for x in (st, pre) if x)

    # ---- sending -------------------------------------------------------
    def send(self, kind, text, in_reply_to=None, summoned=False):
        tag = "DRY-SEND" if self.cfg.dry_run else "LIVE"
        if self.cap_hit() and not self.cfg.dry_run:
            self.log.event("error", f"daily cap ${self.cfg.daily_cap_usd:.2f} reached; not sending (raise with /cap N)")
            return None
        if in_reply_to and not self.cfg.dry_run and not self._reply_budget_ok():
            self.log.event("warn", f"reply limit {self.cfg.max_replies_per_hour}/h reached (live sends); not sending")
            return None
        try:
            tid = self.x.post(text, in_reply_to=in_reply_to)
        except XError as e:
            self._xerr(e, "send failed: ")
            return None
        cost = COST_POST_URL if URL_RE.search(text) else (COST_SUMMONED_REPLY if summoned else COST_POST)
        self._charge(cost, not self.cfg.dry_run)
        if in_reply_to and not self.cfg.dry_run:
            self.state.note_reply_send()
        self.log.event("sent", f"[{tag}] {kind} {tid}" + (f" (reply to {in_reply_to})" if in_reply_to else "") + f": {text}",
                       tweet_id=tid, dry_run=self.cfg.dry_run)
        return tid

    @staticmethod
    def intent_url(in_reply_to, text):
        from urllib.parse import quote
        return f"https://x.com/intent/post?in_reply_to={in_reply_to}&text={quote(text, safe='')}"

    def _is_mention_target(self, d):
        if d.source == "mention":
            return True
        return any(p["id"] == str(d.in_reply_to) and p.get("source") == "mention" for p in self.found)

    def approve(self, did):
        d = self.queue.get(did)
        if d.kind == "reply" and d.grok_text:
            post = next((p.get("text", "") for p in self.found if str(p["id"]) == str(d.in_reply_to)), d.context)
            self.learn_style(d.in_reply_to, post, d.grok_text, d.text)
        if d.kind == "reply" and d.in_reply_to and not self._is_mention_target(d):
            # X blocks API replies to posts that didn't mention you: open the prefilled reply page instead
            from .opener import open_url_async
            d = self.queue.approve(did)
            url = self.intent_url(d.in_reply_to, d.text)
            def done(method):
                self.log.event("sent" if method else "warn",
                               f"#{did} opened in browser: add your own flavor before posting, then press Post" if method
                               else f"#{did}: no browser opener worked; open manually: {url}")
            (self.opener or open_url_async)(url, done)
            self.queue.set_status(did, "sent")
            if d.conversation_id:
                self.state.replied_threads.append(d.conversation_id)
            self.remove_found(d.in_reply_to); self.state.save()
            self.export()
            return d
        d = self.queue.approve(did)
        tid = self.send(d.kind, d.text, d.in_reply_to, summoned=d.source == "mention")
        self.queue.set_status(did, "sent" if tid else "failed")
        if tid and d.in_reply_to:
            if any(str(p["id"]) == str(d.in_reply_to) for p in self.found):
                self.remove_found(d.in_reply_to); self.state.save()
                self.export()
        if tid and d.conversation_id:
            self.state.replied_threads.append(d.conversation_id); self.state.save()
        return d

    def handle(self, c: Command):
        n, ev = c.name, self.log.event
        if n == "pause":
            self.paused = True; ev("ctl", "paused")
        elif n == "resume":
            self.paused = False; ev("ctl", "resumed")
        elif n == "stop":
            self.stopped = True; ev("ctl", "stopping")
        elif n == "align":
            self.cfg.persona = c.text; self.save_config(); ev("align", f"persona set: {c.text}")
        elif n == "posttopics":
            self.cfg.topics = [t.strip() for t in c.text.split(",") if t.strip()]
            self.save_config(); ev("align", f"post topics: {self.cfg.topics}")
        elif n in ("topics", "excluded"):
            cnt = self.tag_counts()
            labels = list(self.taxonomy) + sorted(t for t in cnt if t not in self.taxonomy and t != UNTAGGED)
            ev("info", "tags & X labels (x = excluded, count = found posts): " + "  ".join(
                f"{'x ' if t in self.cfg.excluded_tags else ''}{t}({cnt.get(t, 0)})" for t in labels)
               + f"\nquery: {self.effective_query()[0]}")
        elif n == "filter":
            self.filter_cmd(c.text)
        elif n == "hidden":
            self.show_hidden(all_=c.text.strip().lower() == "all")
        elif n == "block":
            self.set_blocked(set(self.cfg.blocked_authors) | {c.args[0]})
        elif n == "unblock":
            if c.args[0] not in self.cfg.blocked_authors:
                raise KeyError(f"@{c.args[0]} is not blocked")
            self.set_blocked(set(self.cfg.blocked_authors) - {c.args[0]})
        elif n == "blocked":
            ev("info", "block (local): " + (", ".join("@" + h for h in self.cfg.blocked_authors) or "(none)"))
        elif n == "mute":
            self.mute(c.args[0])
        elif n == "unmute":
            self.unmute(c.args[0])
        elif n == "muted":
            m = self.cfg.muted_authors
            ev("info", "mute (real): " + (", ".join(f"@{h}{'' if r.get('live') else ' (dry run, not on X)'}" for h, r in sorted(m.items())) or "(none)"))
        elif n in ("exclude", "include"):
            if ":" in c.text:  # an X label like "entity:Person: Elon Musk" or "link:github.com"
                want = [c.text.strip()]
                known = set(self.tag_counts()) | set(self.cfg.excluded_tags)
            else:
                want = [t.strip().lower().lstrip("#") for t in c.text.replace(",", " ").split() if t.strip()]
                known = set(self.taxonomy)
            bad = [t for t in want if t not in known and not (n == "include" and t in self.cfg.excluded_tags)]
            if bad:
                raise KeyError(f"unknown tag/label(s) {', '.join(bad)}; tags: {', '.join(self.taxonomy)}; "
                               "X labels: see /excluded")
            cur = set(self.cfg.excluded_tags)
            self.set_excluded(cur | set(want) if n == "exclude" else cur - set(want))
        elif n == "model":
            m = c.text.strip()
            if m not in SUPPORTED_MODELS:
                ev("warn", f"model {m!r} is not one of {', '.join(SUPPORTED_MODELS)} (docs.x.ai); using it anyway")
            self.cfg.model = m; self.save_config()
            if hasattr(self.llm, "model"): self.llm.model = m
            ev("ctl", f"model: {m}")
        elif n == "post":
            self._enqueue("post", c.text, source="manual")
        elif n == "reply":
            self._enqueue("reply", c.text, in_reply_to=self.resolve_id(c.args[0]), source="manual")
        elif n == "search":
            if c.text == "help":
                from .help import SEARCH_TIPS
                ev("help", SEARCH_TIPS + f"\n  current query: {self.cfg.search_query}"); return
            self.cfg.search_query = c.text; self.search_since_id = None; self.search_oldest_id = None; self.save_config(); ev("ctl", f"search query: {c.text}")
            from . import search_history; search_history.add(self.state_dir, c.text)
        elif n in ("searchon", "searchoff"):
            self.cfg.search_enabled = n == "searchon"; self.save_config(); ev("ctl", f"search {'ON' if self.cfg.search_enabled else 'OFF'}")
        elif n == "maxresults":
            self.cfg.search_max_results = c.args[0]; self.save_config(); ev("ctl", f"search max_results={c.args[0]}")
        elif n == "maxmentions":
            self.cfg.max_mention_drafts = int(c.args[0]); self.save_config(); ev("ctl", f"max mention drafts={self.cfg.max_mention_drafts} (0=unlimited)")
        elif n == "maxpending":
            self.cfg.max_pending = int(c.args[0]); self.save_config(); ev("ctl", f"max pending drafts={self.cfg.max_pending}")
        elif n == "limit":
            from .credits import limit_summary
            if c.args:
                self.cfg.spend_limit = c.args[0]; self.save_config()
                ev("ctl", "spend limit set: " + limit_summary(self.cfg, self.state))
                self.check_spend_limit()
            else:
                ev("ctl", limit_summary(self.cfg, self.state))
        elif n == "cap":
            self.cfg.daily_cap_usd = c.args[0]; self.save_config(); ev("ctl", f"daily cap ${c.args[0]:.2f} (0=off)")
        elif n == "reads":
            self.cfg.reads_live = {"live": True, "off": False, "auto": None}[c.args[0]]; self.save_config()
            ev("ctl", f"reads {'LIVE (costs X credits)' if self.reads_live() else 'off (fake)'}")
        elif n == "send":
            self.handle(Command("dryrun", [c.args[0]]))
        elif n == "export":
            ev("ctl", f"exported {self.export()} found posts to {self.found_path}")
        elif n == "dryrun":
            self.cfg.dry_run = c.args[0]; self.save_config()
            ev("ctl", f"send {'DRY (logged only)' if c.args[0] else 'LIVE -- approved drafts will be POSTED'}")
        elif n == "approve":
            did = self.resolve_draft(c.args[0]); lbl = self.draft_label(did)
            self.approve(did); self.refill_quick()
        elif n == "reject":
            did = self.resolve_draft(c.args[0]); self.reject_draft(did)
        elif n == "clear" and c.args == ["feed"]:
            self.drafting_hold = True  # auto drafting + prefill paused until F5 (/tick); manual g still works
            hook = getattr(self, "on_clear_feed", None)
            if hook:
                hook()
            ev("info", "feed cleared · drafting paused until F5 (queues, catalog and state unchanged)")
        elif n == "clear":
            src = c.args[0]
            ds = [d for d in self.queue.pending() if (d.source == "mention") == (src == "mention")]
            for d in ds:
                self.queue.reject(d.id)
            # also drop that queue's prefilled drafts, so the cleared queue isn't instantly refilled from the pool
            ids = {str(p["id"]) for p in self.found if (p.get("source") == "mention") == (src == "mention")}
            gone = [k for k in list(self.state.prefill) if k in ids]
            for k in gone:
                self.state.prefill.pop(k)
            self.state.save()
            ev("reject", f"cleared {len(ds)} pending {'mention' if src == 'mention' else 'suggested'} drafts"
                         + (f" and {len(gone)} prefilled" if gone else "") + " (posts stay in the feed; refills under the rate limit)")
        elif n == "style":
            if c.args == ["clear"]:
                ev("info", f"style examples cleared ({self.style.clear()} removed)")
            else:
                k = len(self.style.load())
                ev("info", f"{k} style examples stored, {min(k, self.cfg.style_examples)} used per draft "
                           f"(xbot config style_examples N; 0 disables; /style clear)")
        elif n == "edit":
            did = self.resolve_draft(c.args[0]); lbl = self.draft_label(did)
            self.queue.edit(did, c.text); ev("edit", f"{lbl}: {c.text}")
            if URL_RE.search(c.text): ev("warn", f"{lbl} contains a URL: ${COST_POST_URL:.2f} if sent")
        elif n == "found":
            if c.args and isinstance(c.args[0], int):
                i = c.args[0]
                if not 1 <= i <= len(self.found):
                    raise KeyError(f"no found post #{i}")
                p = self.found[i - 1]
                ev("found", f"#{i} [{p['source']}] id={p['id']} @{p.get('username') or p.get('author_id','?')} "
                   f"{p.get('created_at','')}\n{p['text']}\nhttps://x.com/i/status/{p['id']}  (reply: /reply #{i} <text>)")
            else:
                flt = c.args[0] if c.args else None
                groups = [(s_, t) for s_, t in (("mention", "Mentions"), ("search", "Suggested replies"))
                          if flt in (None, s_)]
                ev("info", f"{len(self.found)} found" + (f" (showing {flt})" if flt else ""))
                for src, title in groups:
                    grp = [(k, p) for k, p in self.feed_found() if p.get("source") == src]
                    self.log.feed_only("section", f"{title} ({len(grp)})")
                    for k, p in grp:
                        self._found_line(k, p)
        elif n == "show":
            from .render import card_plain
            ev("found", card_plain(c.args[0], self.found_post(c.args[0])))
        elif n == "share":
            from .opener import open_url_async
            url = share_url()
            def done(method):
                ev("info", f"opened X compose with the xbot share post via {method}: review and post it in the browser"
                   if method else f"no browser opener worked; open manually: {url}")
            (self.opener or open_url_async)(url, done)
        elif n == "open":
            from .opener import open_url_async
            p = self.found_post(c.args[0]); url = f"https://x.com/i/status/{p['id']}"
            def done(method):
                if method:
                    ev("info", f"opened #{c.args[0]} [post] via {method}")
                else:
                    ev("warn", f"no browser opener worked; open manually: {url}")
            (self.opener or open_url_async)(url, done)
        elif n == "grok":
            if not c.args[0]:
                self.llm = None; ev("ctl", "grok OFF (X-only)")
            else:
                try:
                    self.llm = self.llm_factory() if self.llm_factory else self.llm
                except Exception as e:
                    ev("error", f"grok still off: {e}")
                else:
                    ev("ctl", "grok ON: drafting enabled" if self.llm else "grok: no LLM factory")
                    self.paused = False
                    if self.llm:
                        k = self.refill_from_catalog()
                        if k: ev("info", f"drafted {k} replies from the catalog")
        elif n == "tick":
            if getattr(self, "drafting_hold", False):
                self.drafting_hold = False; ev("ctl", "drafting resumed (F5)")
            k = self.serve_saved()
            if k:
                ev("info", f"F5: showed {k} saved posts (oldest first) · {len(self.saved_left())} saved left"
                   + ("" if self.saved_left() else " · next F5 searches X for new posts"))
                return
            made = self.tick(force_search=True)
            why = ""
            if not self.grok_on:
                why = " (grok off: X-only)"
            elif self.rate_limited() and self.catalog_size():
                why = f" ({self.catalog_size()} waiting; next auto draft in {self.rate_limited()}s)"
            ev("info", f"manual check: {made} drafts{why}")
        elif n == "feed":
            if c.args == ["reset"]:
                self.state.feed_shown = []; self.state.save()
                ev("info", "feed reset: next F5 shows saved posts again from the oldest")
            else:
                ev("info", f"feed: {len(self.feed_found())} loaded · {len(self.saved_left())} saved posts left for F5 (oldest first)")
        elif n == "mentioners":
            ev("align", "filtered mentioners: " + (", ".join("@" + h for h in self.cfg.filtered_mentioners) or "(none)")
               + " · edit in the TUI with /filter mentioners")
        elif n == "backfill":
            self.cfg.search_backfill = c.args[0]; self.save_config()
            ev("ctl", f"search backfill {'ON (older posts fill short searches)' if c.args[0] else 'OFF'}")
        elif n == "status":
            ev("status", self.status())
        elif n == "help":
            from .help import render_help, render_cmd
            ev("help", render_cmd(c.text) if c.text else render_help())

    def status(self):
        st = "STOPPED" if self.stopped else "PAUSED" if self.paused else "RUNNING"
        pend = len(self.queue.pending_capped())
        nm = len(self.queue.pending()) - pend
        full = (" FULL" if self.cfg.max_pending and pend >= self.cfg.max_pending else "") + (f" | mentions={nm}/{self.cfg.max_mention_drafts or '∞'}" if nm else "") + f" | waiting={self.catalog_size()}"
        cap = f"/${self.cfg.daily_cap_usd:.2f}" + (" CAP HIT" if self.cap_hit() else "") if self.cfg.daily_cap_usd else ""
        g = f"grok=on model={self.cfg.model}" if self.grok_on else "grok=off (X-only)"
        return (f"{st} | reads={'live' if self.reads_live() else 'off'} | send={'dry' if self.cfg.dry_run else 'LIVE'} | {g} | found={len(self.found)} | pending={pend}/{self.cfg.max_pending}{full} "
                f"| search={'on' if self.cfg.search_enabled else 'off'} | replies/h={self.state.reply_sends_last_hour()}/"
                f"{self.cfg.max_replies_per_hour} | API ${self.state.api_run_spend():.2f}/${__import__('xbot.credits', fromlist=['x']).effective_limit(self.cfg):.2f} limit "
                f"(X ${self.state.x_run_spend:.2f} + Grok ${self.state.grok_run_spend:.2f})"
                + (f" | X today ${self.state.spent_today():.3f}{cap}" if self.cfg.daily_cap_usd else "") + " "
                f"| last check={self.last_check_str()} | ticks={self.ticks}")

    def last_check_str(self):
        import time
        return time.strftime("%H:%M:%S", time.localtime(self.last_check)) if self.last_check else "never"
