"""The reply queue is a separate list: each item holds its own copy of the post, never a pointer into found."""
import json
from xbot.app import XBotApp
from xbot.llm import FakeLLM
from xbot.queue import DraftQueue
from tests.conftest import queue_predrafts
from tests.test_search import P, S


def _queued(mk, **kw):
    b = mk(FakeLLM(["hi"] * 9), search=[P(1, text="rust 2.0 out"), P(2), P(3)], **S(**kw))
    b.tick(); assert queue_predrafts(b) == 3
    return b


def test_item_holds_its_own_post_copy(mk):
    b = _queued(mk)
    d = next(d for d in b.queue.pending() if d.in_reply_to == "1")
    p = next(p for p in b.found if p["id"] == "1")
    assert d.post["id"] == "1" and d.post["text"] == "rust 2.0 out" and d.post["username"] == "ua1"
    assert d.post["url"] == "https://x.com/i/status/1" and d.post is not p
    p["text"] = "changed in found"; assert d.post["text"] == "rust 2.0 out"  # copy, not a reference


def test_hide_remove_purge_never_touch_queue(mk):
    b = _queued(mk)
    before = [(d.id, d.text, dict(d.post)) for d in b.queue.pending()]
    b.hide_post(1, forever=True)
    b.hide_post(next(i for i, p in enumerate(b.found, 1) if p["id"] == "2"), forever=False, why=["tag x"])
    b.remove_found("3")
    b.found[0]["replied"] = True; b.purge_replied()
    assert [(d.id, d.text, dict(d.post)) for d in b.queue.pending()] == before
    assert all(d.status == "pending" for d in b.queue.items)


def test_old_queue_json_loads_and_backfills(tmp_path):
    path = tmp_path / "queue.json"
    path.write_text(json.dumps({"next": 3, "items": [
        {"id": 1, "kind": "reply", "text": "a", "in_reply_to": "5", "context": "@x: hello", "status": "pending",
         "source": "search", "old_unknown_key": 1},
        {"id": 2, "kind": "reply", "text": "b", "in_reply_to": "6", "status": "sent", "source": "manual"}]}))
    q = DraftQueue(path)
    assert q.items[0].post is None
    q.backfill_posts([{"id": "5", "text": "hello", "username": "x", "media": [{"type": "photo"}]}])
    assert q.items[0].post["text"] == "hello" and q.items[0].post["media"] == [{"type": "photo"}]
    assert q.items[1].post == {"id": "6", "text": "", "url": "https://x.com/i/status/6"}  # gone from found: minimal copy
    assert DraftQueue(path).items[0].post["username"] == "x"  # persisted


async def test_queue_renders_when_post_gone_from_found(mk):
    b = _queued(mk)
    for pid in ("1", "2", "3"):
        b.remove_found(pid)
    assert b.found == [] and len(b.queue.pending()) == 3
    opened = []
    b.opener = lambda url, done: opened.append(url)
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(160, 50)) as pilot:
        app.refresh_ui(); await pilot.pause()
        txt = " ".join(str(l.render()) for l in app.query("#queue Label"))
        assert "@ua1" in txt and "rust 2.0 out" in txt
        d = next(d for d in b.queue.pending() if d.in_reply_to == "1")
        assert app._open_draft_post(d.id) and opened == ["https://x.com/i/status/1"]
        b.stopped = True
