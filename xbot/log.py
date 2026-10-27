"""JSONL action log (~/.local/state/xbot/actions.jsonl) and the in-app feed sink.

Every interesting event (found, draft, approve, mute, …) is written here so you can
audit a session later. Secrets are redacted before writing.
"""
import json, time
from pathlib import Path
from .config import STATE_DIR, redact


class ActionLog:
    def __init__(self, state_dir: Path = None, sink=None):
        self.dir = Path(state_dir or STATE_DIR)
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.dir / "actions.jsonl"
        self.sink = sink  # callable(str) for live feed
        self.rich_sink = None  # callable(rec dict) for colored feed

    def event(self, kind: str, msg: str, **data):
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": kind, "msg": redact(str(msg))}
        rec.update({k: (redact(v) if isinstance(v, str) else v) for k, v in data.items()})
        from .secure import append_private
        append_private(self.path, json.dumps(rec) + "\n")
        self._emit(rec)
        return rec

    def _emit(self, rec):
        if self.rich_sink:
            self.rich_sink(rec)
        elif self.sink:
            self.sink(f"[{rec['ts'][11:19]}] {rec['kind'].upper():8} {rec['msg']}")

    def feed_only(self, kind, msg, **data):
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": kind, "msg": redact(str(msg)), **data}
        self._emit(rec)
        return rec
