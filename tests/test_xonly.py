import pytest
from xbot.commands import parse, CommandError
from xbot.llm import FakeLLM
from xbot.xapi import RealX, XError
from tests.test_search import P, S


def test_xonly_lists_found_no_drafts(mk):
    b = mk(xonly=True, mentions=[{"id": "1234567", "text": "@me hey", "author_id": "u9"}],
           search=[P(i) for i in range(10, 20)], **S(max_pending=1, max_replies_per_hour=1))
    assert b.tick() == 0 and b.queue.pending() == []
    assert len(b.found) == 11 and "grok=off (X-only)" in b.status() and not b.paused
    assert any("x.com/i/status/10" in f and "@ua1" in f for f in b.feed)
    b.handle(parse("/found")); assert any("11 found" in f for f in b.feed[-14:])
    b.handle(parse("/found 2")); assert "id=10" in b.feed[-1]
    with pytest.raises(KeyError): b.handle(parse("/found 99"))


def test_xonly_manual_reply_by_found_ref(mk):
    b = mk(xonly=True, search=[P(42)], **S())
    b.tick()
    b.handle(parse("/reply #1 good point")); d = b.queue.pending()[0]
    assert d.in_reply_to == "42" and b.dry_x.sent == []
    opened = []; b.opener = lambda url, done: (opened.append(url), done("test"))
    b.handle(parse(f"/approve @{d.id}")); assert b.dry_x.sent == [] and "in_reply_to=42" in opened[0]
    assert b.queue.get(d.id).status == "sent"
    m = mk(xonly=True, mentions=[{"id": "7", "text": "@me hi", "author_id": "m"}], **S()); m.tick()
    n7 = next(i for i, p in enumerate(m.found, 1) if p["id"] == "7")
    m.handle(parse(f"/reply #{n7} thanks")); m.handle(parse(f"/approve @{m.queue.pending()[0].id}"))
    assert m.dry_x.sent[0]["in_reply_to"] == "7"  # mentions still go through the API
    b.handle(parse("/post hi")); assert b.queue.pending()[0].text == "hi"
    with pytest.raises(KeyError): b.handle(parse("/reply #9 x"))
    with pytest.raises(CommandError): parse("/reply #x hi")


def test_grok_on_enables_drafting(mk):
    keys = []
    def factory():
        if not keys: raise RuntimeError("XAI_API_KEY not set")
        return FakeLLM(["drafted"])
    b = mk(xonly=True, llm_factory=factory, search=[P(1)], **S())
    b.handle(parse("/grok on")); assert not b.grok_on and "still off" in b.feed[-1]
    keys.append(1); b.handle(parse("/grok on")); assert b.grok_on
    b.dry_x.fake_search = [P(2)]; assert b.tick() == 1 and "grok=on" in b.status()
    b.handle(parse("/grok off")); assert not b.grok_on


def test_realx_missing_keys_clear_message(mk, monkeypatch):
    for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(XError, match="missing X credentials"): RealX()
    b = mk(xonly=True, **S()); b.real_x_factory = RealX
    b.handle(parse("/dryrun off")); b.handle(parse("/reads live"))
    b.tick(); b.tick()  # no crash, logged once
    assert sum("missing X credentials" in f for f in b.feed) == 1
    b.handle(parse("/post x")); b.handle(parse(f"/approve @{b.queue.pending()[0].id}"))
    assert b.queue.items[-1].status == "failed"
