"""Style learning: (post, Grok draft, user's final text) records from edited drafts, used as few-shot examples."""
import json
from pathlib import Path

KEEP = 50
CLIP = 240


def _clip(s, n=CLIP):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


class StyleStore:
    def __init__(self, path):
        self.path = Path(path) if path else None

    def load(self):
        if not self.path or not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def add(self, post_id, post, draft, final):
        if not self.path or not final or final.strip() == (draft or "").strip():
            return False
        recs = self.load() + [{"id": str(post_id or ""), "post": _clip(post), "draft": _clip(draft), "final": _clip(final, 280)}]
        recs = recs[-KEEP:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        from .secure import write_private
        write_private(self.path, "".join(json.dumps(r) + "\n" for r in recs))
        return True

    def clear(self):
        n = len(self.load())
        if self.path and self.path.exists():
            self.path.unlink()
        return n


def examples_block(recs, n, excluded_ids=()):
    if n <= 0:
        return ""
    recs = [r for r in recs if str(r.get("id")) not in excluded_ids][-n:]
    if not recs:
        return ""
    lines = ["\nExamples of replies in the user's voice (post, then how the user rewrote the draft). Match this voice:"]
    for r in recs:
        lines.append(f"- Post: {_clip(r.get('post'), 160)}\n  Draft: {_clip(r.get('draft'), 120)}\n  User's reply: {_clip(r.get('final'), 200)}")
    return "\n".join(lines)
