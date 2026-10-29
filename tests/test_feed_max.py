"""FIFO feed: saved posts are served oldest first, FEED_MAX per F5; then F5 searches X. found.json keeps all."""
import asyncio, json
from xbot.app import FeedLog
from xbot.commands import parse
from xbot.state import BotState


def posts(k, media_at=()):
    return [{"id": str(1000 + i), "text": f"post {i} https://t.co/x", "source": "search", "tags": [], "username": f"u{i}",
             **({"media": [{"type": "photo", "url": f"https://pbs.twimg.com/{i}.jpg"}]} if i in media_at else {})}
            for i in range(k)]


def shown(recs):
    return [r["n"] for r in recs if r.get("tweet_id")]


def test_startup_first_page_then_f5_pages_fifo_then_search(mk):
    b = mk(xonly=True); recs = []; b.log.rich_sink = recs.append
    b.found = posts(250, media_at=(0,)); b.export()
    for p in b.found[:30]:
        p["user_hidden"] = True  # like his blocked-author posts: skipped
    calls = []; b.tick = lambda **k: calls.append(k) or 0
    b.replay_found()
    assert shown(recs) == list(range(31, 131))  # oldest visible first
    recs.clear(); b.handle(parse("/tick"))
    assert shown(recs) == list(range(131, 231)) and not calls  # F5: next saved page, no X search/drafting
    recs.clear(); b.handle(parse("/tick"))
    assert shown(recs) == list(range(231, 251)) and not calls
    recs.clear(); b.handle(parse("/tick"))
    assert shown(recs) == [] and calls == [{"force_search": True}]  # all served: search X
    assert len(json.loads(b.found_path.read_text())["posts"]) == 250  # nothing deleted
    assert b.found_post(5)["id"] == "1004"


def test_cursor_survives_restart_clear_and_reset(mk, tmp_path):
    b = mk(xonly=True); recs = []; b.log.rich_sink = recs.append
    b.found = posts(250); b.tick = lambda **k: 0
    b.replay_found(); b.handle(parse("/tick"))
    assert len(BotState(b.state.path).feed_shown) == 200
    b.state = BotState(b.state.path)  # restart: startup redraws the current page
    recs.clear(); b.replay_found()
    assert shown(recs) == list(range(101, 201))
    b.handle(parse("/clear")); recs.clear(); b.handle(parse("/tick"))
    assert shown(recs) == list(range(201, 251))  # /clear keeps the cursor
    b.handle(parse("/feed reset")); recs.clear(); b.handle(parse("/tick"))
    assert shown(recs) == list(range(1, 101))


def test_new_posts_join_end_and_are_not_served_again(mk):
    b = mk(xonly=True, search=[{"id": "9001", "text": "new", "author_id": "1"}])
    b.found = posts(5); b.replay_found()
    b._remember({"id": "9001", "text": "new", "author_id": "1"}, "search")
    assert b.saved_left() == [] and b.feed_found()[-1][1]["id"] == "9001"


def test_feedlog_drops_oldest_post_lines():
    async def run():
        from textual.app import App
        class A(App):
            def compose(self):
                yield FeedLog(id="feed")
        async with A().run_test() as pilot:
            f = pilot.app.query_one(FeedLog); f.max_posts = 3
            f.write("section")
            for i in range(5):
                f.write(f"p{i}", post=True)
            await pilot.pause()
            assert f._items == ["section", "p2", "p3", "p4"] and sum(f._posts) == 3
    asyncio.run(run())
