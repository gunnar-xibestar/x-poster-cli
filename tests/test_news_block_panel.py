import json
from textual.widgets import Static, SelectionList
from xbot.commands import parse, CommandError
from xbot.tags import tag_text, tag_post, build_query, label_ids
from xbot.app import XBotApp, PostCard, Confirm, TagPicker
from xbot.render import drafts_title, drafts_placeholder
from xbot.llm import FakeLLM
from tests.test_search import P, S
import pytest


def test_news_tag_and_untagged():
    for t in ("BREAKING: plant fire downtown", "\U0001F6A8 JUST IN: something", "Developing story",
              "Report: deal is off", "according to officials", "today's headlines"):
        assert "news" in tag_text(t), t
    assert "news" not in tag_text("reporting tool")
    assert tag_post({"text": "x", "context_annotations": [{"domain": {"name": "News"}, "entity": {"name": "X"}}]}) == ["news"]
    assert label_ids({"tags": [], "xlabels": {}}) == []
    assert "untagged" not in label_ids({"tags": ["ai"]})
    assert build_query("q", ["untagged"])[0] == "q"


def test_exclude_untagged_and_news(mk):
    b = mk(xonly=True, search=[P(1, text="BREAKING: storm"), P(2, text="hello there"), P(3, text="rust tips")], **S())
    b.tick()
    import pytest
    with pytest.raises(KeyError):
        b.handle(parse("/exclude untagged"))  # pseudo-tag removed
    b.handle(parse("/exclude news"))
    assert [p["id"] for _, p in b.visible_found()] == ["2", "3"]
    assert "-breaking" in b.effective_query()[0]


def test_block_unblock_query_and_mentions_dimmed(mk):
    b = mk(xonly=True, mentions=[{"id": "1", "text": "@me hi", "author_id": "x", "username": "ExampleUser"}],
           search=[P(10, author="exampleuser"), P(11)], **S())
    b.handle(parse("/block @ExampleUser"))
    assert b.cfg.blocked_authors == ["exampleuser"]
    assert b.effective_query()[0].startswith(b.cfg.search_query + " -from:exampleuser")  # from-terms first
    for p in b.dry_x.fake_search: p["username"] = p["author_id"] if p["id"] == "10" else "ok"
    b.tick()
    assert "-from:exampleuser" in b.dry_x.searches[-1]
    assert [p["id"] for _, p in b.visible_found()] == ["1", "11"]  # mention visible, blocked search post dropped
    recs = []; b.log.rich_sink = recs.append; b.replay_found()
    m = [r for r in recs if r.get("kind") == "found" and r["tweet_id"] == "1"][0]
    assert m["blocked"]
    from xbot.render import feed_markup
    assert "blocked (local)" in feed_markup(m)
    b.handle(parse("/blocked")); assert "@exampleuser" in recs[-1]["msg"]
    b.handle(parse("/unblock exampleuser")); assert b.cfg.blocked_authors == []
    with pytest.raises(KeyError): b.handle(parse("/unblock nobody"))
    with pytest.raises(CommandError): parse("/block @bad-handle!")


def test_query_limit_with_blocks():
    q, a, d = build_query("x" * 500, [], blocked=["aaaaaaaaaa", "b"])
    assert len(q) <= 512 and d == 1 and q.endswith(" -from:b")


def test_retag_on_startup(mk):
    b = mk(xonly=True, search=[P(1, text="BREAKING: thing")], **S()); b.tick()
    data = json.loads(b.found_path.read_text()); data["posts"][0]["tags"] = []
    b.found_path.write_text(json.dumps(data))
    b2 = mk(xonly=True); assert b2.found[0]["tags"] == ["news"]


async def test_card_b_blocks_with_confirm(mk):
    b = mk(xonly=True, search=[P(1, author="spammy"), P(2)], **S()); b.tick()
    opened = []; b.opener = lambda url, done: (opened.append(url), done("test"))
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app.action_show_post(1); await pilot.pause()
        await pilot.press("b"); await pilot.pause(); assert isinstance(app.screen, Confirm)
        await pilot.press("n"); await pilot.pause(); assert b.cfg.blocked_authors == []
        await pilot.press("b"); await pilot.pause(); await pilot.press("y"); await pilot.pause()
        assert b.cfg.blocked_authors == ["uspammy"] and isinstance(app.screen, PostCard)
        assert opened == ["https://x.com/uspammy"]
        await pilot.press("escape"); await pilot.pause()
        app._run("/topics"); await pilot.pause()
        sl = app.screen.query_one(SelectionList)
        assert "@uspammy" in sl.selected
        sl.deselect("@uspammy"); await pilot.press("enter"); await pilot.pause()
        assert b.cfg.blocked_authors == []


async def test_drafts_panel_title_and_placeholder(mk):
    b = mk(xonly=True)
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 40)) as pilot:
        app.refresh_ui(); await app.workers.wait_for_complete(); await pilot.pause()
        box = app.query_one("#drafts")
        assert box.border_title == "Auto replies (Grok drafts) 0/4"
        assert "approve" in box.border_subtitle and "reject" in box.border_subtitle
        ph = app.query_one("#queue-empty", Static)
        assert ph.display and "Grok off" in str(ph.render())
        b.handle(parse("/post hi")); app.refresh_ui(); await app.workers.wait_for_complete(); await pilot.pause()
        assert box.border_title.endswith("1/4") and not ph.display
    b2 = mk(llm=FakeLLM())
    for d in b2.queue.pending(): b2.queue.reject(d.id)
    assert "No drafts yet" in drafts_placeholder(b2) and drafts_title(b2).startswith("Auto replies")
