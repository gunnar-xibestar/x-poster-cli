import json
from xbot.oembed import fetch_author, fetch_many, ENDPOINT
from xbot.app import XBotApp, PostCard
from xbot.render import card_renderable
from tests.test_search import S


class Resp:
    def __init__(self, code, data=None, bad=False):
        self.status_code, self._d, self._bad = code, data, bad
    def json(self):
        if self._bad: raise ValueError("not json")
        return self._d


def test_fetch_author_parses_and_is_polite():
    seen = {}
    def get(url, params=None, headers=None, timeout=None):
        seen.update(url=url, params=params, headers=headers, timeout=timeout)
        return Resp(200, {"author_name": "jack", "author_url": "https://x.com/jack"})
    assert fetch_author("20", get=get) == {"name": "jack", "username": "jack"}
    assert seen["url"] == ENDPOINT == "https://publish.x.com/oembed"
    assert seen["params"]["url"] == "https://twitter.com/i/status/20" and seen["params"]["dnt"] == "true"
    assert "xbot" in seen["headers"]["User-Agent"] and seen["timeout"] <= 10


def test_fetch_author_failures_return_none_once():
    calls = []
    def mk(r):
        def get(*a, **k):
            calls.append(1)
            if isinstance(r, Exception): raise r
            return r
        return get
    for r in (Resp(404), Resp(405), Resp(200, bad=True), Resp(200, {"author_url": ""}), TimeoutError("slow")):
        calls.clear(); assert fetch_author("1", get=mk(r)) is None and len(calls) == 1  # no retries


def test_fetch_many_dedup():
    got = []
    res = fetch_many(["1", "2", "1"], fetch=lambda t: got.append(t) or {"name": "n" + t, "username": "u" + t})
    assert sorted(got) == ["1", "2"] and res["2"]["username"] == "u2"


def raw(i):
    return {"id": str(i), "text": "linux thing", "author_id": f"a{i}", "conversation_id": str(i)}


def test_prefetch_fills_handles_on_check(mk):
    b = mk(xonly=True, mentions=[raw(1)], search=[raw(10), raw(11)], **S())
    b.author_fetch = lambda tid: None if tid == "11" else {"name": "Name" + tid, "username": "h" + tid}
    b.tick()
    by = {p["id"]: p for p in b.found}
    assert by["1"]["username"] == "h1" and by["10"]["name"] == "Name10"
    assert by["11"].get("username") is None and by["11"]["author_lookup"] == "failed"
    assert any("@h10" in f for f in b.feed) and any("@a11" in f for f in b.feed)  # fallback author_id
    f = {p["id"]: p for p in json.loads(b.found_path.read_text())["posts"]}
    assert f["10"]["username"] == "h10" and f["11"]["author_lookup"] == "failed"


def test_lazy_lookup_cached_and_no_retry_after_failure(mk):
    b = mk(xonly=True, search=[raw(5), raw(6)], **S(oembed_prefetch=False)); b.tick()
    calls = []
    b.author_fetch = lambda tid: calls.append(tid) or ({"name": "Ann", "username": "ann"} if tid == "5" else None)
    assert b.lookup_author(1)["username"] == "ann"; b.lookup_author(1)
    b.lookup_author(2); b.lookup_author(2)
    assert calls == ["5", "6"]  # cached / failure not retried
    from rich.console import Console
    c = Console(width=120, record=True); c.print(card_renderable(2, b.found[1], b))
    out = c.export_text(); assert "author a6" in out and "lookup failed" in out
    b.found.append({"id": "9", "text": "x", "source": "search"})
    c = Console(width=120, record=True); c.print(card_renderable(3, b.found[2], b))
    assert "unknown author" in c.export_text()


async def test_card_open_triggers_background_lookup(mk):
    b = mk(xonly=True, search=[raw(5), raw(6)], **S(oembed_prefetch=False)); b.tick()
    b.author_fetch = lambda tid: {"name": "Name" + tid, "username": "h" + tid}
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app.action_show_post(1); await pilot.pause()
        await app.workers.wait_for_complete(); await pilot.pause()
        assert b.found[0]["username"] == "h5" and isinstance(app.screen, PostCard)
        await pilot.press("right"); await app.workers.wait_for_complete(); await pilot.pause()
        assert b.found[1]["username"] == "h6"
    assert json.loads(b.found_path.read_text())["posts"][1]["username"] == "h6"
