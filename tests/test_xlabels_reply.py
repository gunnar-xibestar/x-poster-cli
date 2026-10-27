import json
from textual.widgets import TextArea, SelectionList
from xbot.commands import parse
from xbot.llm import FakeLLM
from xbot.tags import x_labels, label_ids, build_query
from xbot.app import XBotApp, PostCard, ReplyEditor, TagPicker
from xbot.render import card_renderable
from tests.test_search import P, S


def XP(i=5):
    p = P(i, text="$TSLA up, Elon Musk says AI. github.com/x/y")
    p["context_annotations"] = [{"domain": {"name": "Technology"}, "entity": {"name": "Artificial intelligence"}},
                                {"domain": {"name": "Technology"}, "entity": {"name": "Artificial intelligence"}}]
    p["entities"] = {"annotations": [{"type": "Person", "normalized_text": "Elon Musk", "probability": 0.9},
                                     {"type": "Other", "normalized_text": "Stuff", "probability": 0.9},
                                     {"type": "Organization", "normalized_text": "Meh", "probability": 0.3}],
                     "cashtags": [{"tag": "tsla"}],
                     "urls": [{"expanded_url": "https://www.github.com/x/y"}, {"expanded_url": "https://x.com/a/status/1"}]}
    return p


def test_x_labels_extraction():
    xl = x_labels(XP())
    assert xl == {"topics": ["Technology › Artificial intelligence"], "entities": ["Person: Elon Musk"],
                  "cashtags": ["$TSLA"], "links": ["github.com"]}
    ids = label_ids({"tags": ["ai"], "xlabels": xl})
    assert ids == ["ai", "topic:Technology › Artificial intelligence", "entity:Person: Elon Musk", "cashtag:$TSLA", "link:github.com"]
    q = build_query("q", ["link:github.com", "entity:Person: Elon Musk", "cashtag:$TSLA", "topic:Technology › Artificial intelligence"])[0]
    assert q == 'q -url:github.com -"Elon Musk"'


def test_xlabels_stored_hidden_and_card(mk):
    b = mk(xonly=True, search=[XP(5), P(6, text="plain")], **S()); b.tick()
    f = json.loads(b.found_path.read_text())["posts"][0]
    assert f["xlabels"]["cashtags"] == ["$TSLA"] and "entities" not in b.found[0]
    b.handle(parse("/exclude cashtag:$TSLA"))
    assert [p["id"] for _, p in b.visible_found()] == ["6"]
    b.handle(parse("/include cashtag:$TSLA")); assert b.cfg.excluded_tags == []
    from rich.console import Console
    c = Console(width=120, record=True); c.print(card_renderable(1, b.found[0], b)); out = c.export_text()
    for s in ("X topics", "Technology › Artificial intelligence", "Entities", "Person: Elon Musk", "Cashtags", "Links", "github.com", "draft reply", "block (verify)", "mute (real)"):
        assert s in out
    b.handle(parse("/excluded")); assert "link:github.com(1)" in b.feed[-1]


async def test_card_picker_lists_x_labels(mk):
    b = mk(xonly=True, search=[XP(5)], **S()); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app.action_show_post(1); await pilot.pause()
        await pilot.press("t"); await pilot.pause()
        assert type(app.screen).__name__ == "FilterOptions" and "tag:link:github.com" in [v for v, _ in b.filter_options(b.found[0])]


async def test_g_with_grok_drafts_and_sends_dry(mk):
    llm = FakeLLM(["first draft", "second draft"])
    b = mk(llm=llm, search=[], **S())
    b.found.append({"id": "77", "text": "rust 2.0", "source": "mention", "tags": ["rust"], "username": "ann"})
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app.action_show_post(1); await pilot.pause()
        await pilot.press("g"); await app.workers.wait_for_complete(); await pilot.pause()
        ed = app.screen; assert isinstance(ed, ReplyEditor)
        assert ed.query_one(TextArea).text == "first draft"
        assert "rust" in llm.calls[0][1] and "@ann" in llm.calls[0][1]
        await pilot.press("ctrl+g"); await app.workers.wait_for_complete(); await pilot.pause()
        assert ed.query_one(TextArea).text == "second draft"
        await pilot.press("ctrl+s"); await pilot.pause()
        assert isinstance(app.screen, PostCard)
    assert b.dry_x.sent == [{"id": b.dry_x.sent[0]["id"], "text": "second draft", "in_reply_to": "77"}]
    assert b.found[0]["replied"] and json.loads(b.found_path.read_text())["posts"][0]["replied"]


async def test_g_without_grok_empty_editor_queue_and_cancel(mk):
    b = mk(xonly=True, search=[P(8, text="linux")], **S()); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app.action_show_post(1); await pilot.pause()
        await pilot.press("g"); await pilot.pause()
        ed = app.screen; assert isinstance(ed, ReplyEditor) and ed.query_one(TextArea).text == ""
        await pilot.press("ctrl+s"); await pilot.pause(); assert isinstance(app.screen, ReplyEditor)  # empty: not sent
        ed.query_one(TextArea).text = "see example.com"; await pilot.pause()
        assert "$0.20" in str(ed.query_one("#ed-info").render())
        ed.query_one(TextArea).text = "x" * 281; await pilot.pause()
        await pilot.press("ctrl+s"); await pilot.pause(); assert b.dry_x.sent == []
        ed.query_one(TextArea).text = "nice one"; await pilot.press("ctrl+e"); await pilot.pause()
        assert b.queue.pending()[-1].text == "nice one" and b.queue.pending()[-1].in_reply_to == "8"
        await pilot.press("g"); await pilot.pause(); await pilot.press("escape"); await pilot.pause()
        assert isinstance(app.screen, PostCard) and b.dry_x.sent == []


def test_live_send_failure_on_search_post_gives_hint(mk):
    from xbot.xapi import XError
    class R:
        def post(self, text, in_reply_to=None): raise XError("X API 403 forbidden")
    b = mk(xonly=True); b.real_x_factory = R
    b.found.append({"id": "9", "text": "t", "source": "search"})
    b.handle(parse("/send live"))
    assert b.send_reply_to_found(1, "hi") is None and "summoned" in b.feed[-1] and not b.found[0].get("replied")


def test_no_user_read_cost(mk):
    class R:
        def mentions(self, s=None): return []
        def me(self): return "me"
        def search_recent(self, q, n, s=None, **k): return [] if k.get("until_id") else [P(1), P(2), P(3)]
    r = R()
    b = mk(xonly=True, **S()); b.real_x_factory = lambda: r
    b.handle(parse("/reads live")); b.tick()
    assert round(b.state.spent_today(), 3) == 0.015  # 3 post reads only


async def test_card_arrow_navigation(mk):
    b = mk(xonly=True, mentions=[{"id": "1", "text": "@me hi", "author_id": "m"}],
           search=[P(10, text="rust"), P(11, text="bitcoin"), P(12, text="linux")], **S())
    b.tick()  # found: 1=mention, 2=rust, 3=bitcoin, 4=linux
    b.handle(parse("/exclude crypto"))
    assert b.nav_order() == [1, 2, 4]
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app.action_show_post(1); await pilot.pause()
        card = app.screen
        await pilot.press("left"); await pilot.pause(); assert card.n == 1  # stop at start
        await pilot.press("right"); await pilot.pause(); assert card.n == 2
        await pilot.press("j"); await pilot.pause(); assert card.n == 4  # skips hidden #3
        await pilot.press("down"); await pilot.pause(); assert card.n == 4  # stop at end
        await pilot.press("k"); await pilot.pause(); assert card.n == 2
        await pilot.press("up"); await pilot.pause(); assert card.n == 1
    from rich.console import Console
    c = Console(width=120, record=True); c.print(card_renderable(2, b.found[1], b))
    assert "2/3" in c.export_text()


async def test_search_post_ctrl_s_does_not_send(mk):
    b = mk(xonly=True, search=[P(8, text="linux")], **S()); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app.action_show_post(1); await pilot.pause()
        await pilot.press("g"); await pilot.pause()
        ed = app.screen; ed.query_one(TextArea).text = "nice"; await pilot.pause()
        info = str(ed.query_one("#ed-info").render())
        assert "Ctrl+S" not in info and "Ctrl+B" in info and "Ctrl+O" not in info
        await pilot.press("ctrl+s"); await pilot.pause()
        assert isinstance(app.screen, ReplyEditor) and b.dry_x.sent == []
