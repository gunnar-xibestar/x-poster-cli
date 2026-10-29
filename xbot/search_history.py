"""Local search history (search_history.json in the state dir, 0600): deduped, newest first, capped."""
import json
from pathlib import Path

CAP = 100
NAME = "search_history.json"


def _path(state_dir):
    return Path(state_dir) / NAME


def load(state_dir):
    try:
        v = json.loads(_path(state_dir).read_text())
        return [q for q in v if isinstance(q, str) and q.strip()][:CAP] if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def add(state_dir, query):
    q = " ".join(str(query or "").split())
    if not q:
        return load(state_dir)
    items = [q] + [x for x in load(state_dir) if x.casefold() != q.casefold()]
    items = items[:CAP]
    try:
        from .secure import write_private
        write_private(_path(state_dir), json.dumps(items, indent=1))
    except ImportError:
        p = _path(state_dir); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(items, indent=1)); p.chmod(0o600)
    except OSError:
        pass
    return items
