"""Pending reply drafts waiting for your approve / reject / edit.

Mentions and suggested replies share one list, shown in two sections in the UI.
Drafts survive a restart via state_dir/queue.json.
"""
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class Draft:
    id: int
    kind: str  # "post" | "reply"
    text: str
    in_reply_to: Optional[str] = None
    context: str = ""
    status: str = "pending"  # pending|approved|rejected|sent|failed
    source: str = "bot"  # bot|mention|search|manual
    conversation_id: Optional[str] = None
    grok_text: Optional[str] = None  # original Grok draft (style learning)
    post: Optional[dict] = None  # own copy of the replied-to post (id, text, author, url, media...): independent of found/search


def snapshot_post(p):
    """Deep copy of a found/search post for a queue item (never a reference into found)."""
    import copy
    if not p:
        return None
    c = copy.deepcopy({k: v for k, v in p.items() if k not in ("user_hidden", "hide_why", "replied")})
    c["id"] = str(c.get("id"))
    c.setdefault("url", f"https://x.com/i/status/{c['id']}")
    return c


class DraftQueue:
    """Draft queue, optionally persisted to a JSON file after every change."""

    def __init__(self, path: Path = None):
        self.path = Path(path) if path else None
        self.items: list[Draft] = []
        self._next = 1
        if self.path and self.path.exists():
            data = json.loads(self.path.read_text())
            fields = set(Draft.__dataclass_fields__)
            self.items = [Draft(**{k: v for k, v in d.items() if k in fields}) for d in data.get("items", [])]
            self._next = data.get("next", len(self.items) + 1)

    def backfill_posts(self, found):
        """Old queue.json items have no post copy: copy it from found once (if still there), else a minimal one."""
        by_id = {str(p["id"]): p for p in found or []}
        changed = False
        for d in self.items:
            if d.post is None and d.in_reply_to:
                src = by_id.get(str(d.in_reply_to))
                d.post = snapshot_post(src) if src else {"id": str(d.in_reply_to), "text": d.context or "",
                                                          "url": f"https://x.com/i/status/{d.in_reply_to}"}
                changed = True
        if changed:
            self._save()
        return changed

    def _save(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # keep pending + last 200 finished
            done = [d for d in self.items if d.status != "pending"][-200:]
            self.items = [d for d in self.items if d.status == "pending" or d in done]
            from .secure import write_private
            write_private(self.path, json.dumps({"next": self._next, "items": [asdict(d) for d in self.items]}))

    def add(self, kind, text, in_reply_to=None, context="", source="bot", conversation_id=None, grok_text=None, post=None):
        d = Draft(self._next, kind, text, in_reply_to, context, source=source, conversation_id=conversation_id,
                  grok_text=grok_text, post=post)
        self._next += 1
        self.items.append(d)
        self._save()
        return d

    def pending(self):
        """Pending drafts, replies to mentions first (they don't count toward the queue limit)."""
        ps = [d for d in self.items if d.status == "pending"]
        return [d for d in ps if d.source == "mention"] + [d for d in ps if d.source != "mention"]

    def pending_capped(self):
        """Pending drafts that count toward max_pending (everything except mention replies)."""
        return [d for d in self.items if d.status == "pending" and d.source != "mention"]

    def get(self, did):
        for d in self.items:
            if d.id == did:
                return d
        raise KeyError(did)

    def _check(self, did):
        d = self.get(did)
        if d.status != "pending":
            raise ValueError(f"draft {did} is {d.status}")
        return d

    def set_status(self, did, status):
        d = self.get(did); d.status = status; self._save(); return d

    def approve(self, did):
        self._check(did); return self.set_status(did, "approved")

    def reject(self, did):
        self._check(did); return self.set_status(did, "rejected")

    def delete(self, did):
        d = self.get(did); self.items.remove(d); self._save(); return d

    def edit(self, did, text):
        d = self._check(did); d.text = text; self._save(); return d
