from xbot.commands import parse
from xbot.xapi import RealX
from tests.test_search import P, S


def M(i):
    return {"id": str(i), "text": f"@me q{i}", "author_id": f"m{i}", "username": f"m{i}", "conversation_id": str(i)}


def test_check_order_mentions_then_suggestions(mk):
    b = mk(xonly=True, mentions=[M(i) for i in range(1, 26)], search=[P(i) for i in range(100, 130)], **S())
    b.handle(parse("/tick"))
    sec = [f for f in b.feed if "SECTION" in f]
    assert "Mentions (25 new)" in sec[0] and "Suggested replies (10)" in sec[1]
    i_m = next(i for i, f in enumerate(b.feed) if "Mentions (25" in f)
    i_s = next(i for i, f in enumerate(b.feed) if "Suggested replies" in f)
    assert all("[mention]" in f for f in b.feed[i_m + 1:i_s] if "FOUND" in f)
    assert len([f for f in b.feed[i_s:] if "[search]" in f]) == 10
    assert len(b.found) == 35


def test_found_lists_all_and_filters(mk):
    b = mk(xonly=True, mentions=[M(i) for i in range(1, 4)], search=[P(i) for i in range(100, 140)],
           **S(search_max_results=40))
    b.tick(); b.feed.clear()
    b.handle(parse("/found")); assert len([f for f in b.feed if "FOUND" in f]) == 43
    b.feed.clear(); b.handle(parse("/found mentions"))
    assert len([f for f in b.feed if "FOUND" in f]) == 3 and not any("[search]" in f for f in b.feed)
    b.feed.clear(); b.handle(parse("/found search")); assert len([f for f in b.feed if "[search]" in f]) == 40


def test_replay_mentions_first(mk):
    b = mk(xonly=True, search=[P(100)], **S()); b.tick()
    b.dry_x.fake_mentions = [M(1)]; b.tick()
    b2 = mk(xonly=True); recs = []; b2.log.rich_sink = recs.append
    b2.replay_found()
    srcs = [r["source"] for r in recs if r["kind"] == "found"]
    assert srcs == ["mention", "search"]


def test_realx_mentions_paginates_with_cap(monkeypatch):
    for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"):
        monkeypatch.setenv(k, "v")
    x = RealX(); x._uid = "me"; calls = []
    def req(method, path, params=None, **kw):
        calls.append(dict(params))
        page = len(calls)
        return {"data": [{"id": str(page * 100 + i), "text": "t", "author_id": "a"} for i in range(40)],
                "includes": {"users": [{"id": "a", "username": "al"}]},
                "meta": {"next_token": f"tok{page}"} if page < 5 else {}}
    x._req = req
    out = x.mentions(since_id="9", cap=100)
    assert len(out) == 100 and len(calls) == 3 and calls[1]["pagination_token"] == "tok1"
    assert calls[0]["since_id"] == "9" and calls[0].get("expansions").startswith("attachments.media_keys") and "user.fields" not in calls[0]
    calls.clear(); x2 = x.mentions(cap=1000); assert len(x2) == 200 and len(calls) == 5
