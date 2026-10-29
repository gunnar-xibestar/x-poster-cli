from textual.widgets import Input, SelectionList
from xbot.app import XBotApp, MentionersEditor, ReplyEditor
from test_search import P, S


async def test_mentioners_editor_toggle_add_save(mk):
    b = mk(filtered_mentioners=["spammy_sam", "bot_bob"])
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app._run("/filter mentioners"); await pilot.pause()
        scr = app.screen; assert isinstance(scr, MentionersEditor)
        await pilot.press("space"); await pilot.pause()  # uncheck @spammy_sam
        await pilot.press("tab"); await pilot.press(*"@NewGuy"); await pilot.press("enter"); await pilot.pause()
        assert scr.query_one(Input).value == ""
        await pilot.press("tab"); await pilot.press("enter"); await pilot.pause()
        assert not isinstance(app.screen, MentionersEditor)
    assert b.cfg.filtered_mentioners == ["bot_bob", "newguy"]


async def test_mentioners_alias_and_cancel(mk):
    b = mk(filtered_mentioners=["x1"])
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app._run("/mentioners"); await pilot.pause()
        assert isinstance(app.screen, MentionersEditor)
        await pilot.press("space"); await pilot.press("escape"); await pilot.pause(); await pilot.pause()
    assert b.cfg.filtered_mentioners == ["x1"]


async def test_xonly_empty_xai_key_works(mk, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "")
    from xbot.llm import GrokLLM
    b = mk(xonly=True, mentions=[{"id": "1", "text": "@me hi", "author_id": "m"}], search=[P(10), P(11)],
           llm_factory=lambda: GrokLLM("grok-4.7", "https://api.x.ai/v1"), **S())
    assert not b.grok_on
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app._run("/tick"); await pilot.pause()
        assert len(b.found) == 3
        app._run("/grok on"); await pilot.pause()
        assert not b.grok_on and any("grok still off" in l for l in (b.log.dir / "actions.jsonl").read_text().splitlines())
        app.action_show_post(2); await pilot.pause()
        await pilot.press("g"); await pilot.pause()
        assert isinstance(app.screen, ReplyEditor)
        await pilot.press("ctrl+g"); await pilot.pause()  # no-op without Grok
        await pilot.press(*"hello"); await pilot.press("ctrl+e"); await pilot.pause()
        app.refresh_ui(); await pilot.pause()
    assert [d.text for d in b.queue.pending()] == ["hello"]


async def test_card_h_no_hides_forever(mk):
    from xbot.app import PostCard
    b = mk(xonly=True, search=[P(10), P(11), P(12)], **S())
    b.tick()
    b.queue.add("reply", "draft for 11", in_reply_to="11", source="search")
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app.action_show_post(2); await pilot.pause()
        await pilot.press("h"); await pilot.pause(); await pilot.pause()
        assert b.found[1].get("user_hidden") == "forever" and 2 not in b.nav_order()
        assert isinstance(app.screen, PostCard) and app.screen.n != 2
        assert b.queue.pending() == [] and "11" in b.state.seen
        assert all(l != "#2" for l, _, _ in b.hidden_list())


async def test_card_h_yes_applies_filters_and_restore(mk):
    from xbot.app import FilterOptions, HiddenPicker
    b = mk(xonly=True, search=[P(10, text="Huge memecoin presale today"), P(11), P(12)], **S())
    b.tick()
    opts = b.filter_options(b.found[0])
    assert ("topic:crypto-shill", "hide broad topic crypto-shill") in opts and ("word:memecoin", "hide word memecoin") in opts
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app.action_show_post(1); await pilot.pause()
        await pilot.press("t"); await pilot.pause()
        scr = app.screen; assert isinstance(scr, FilterOptions)
        sl = scr.query_one(SelectionList); sl.select("topic:crypto-shill")
        await pilot.press("enter"); await pilot.pause()
        assert "crypto-shill" in b.cfg.filter_topics and b.found[0].get("user_hidden") is True
        assert any(l == "#1" and any("hidden by you: topic crypto-shill" in w for w in why) for l, _, why in b.hidden_items())
        while len(app.screen_stack) > 1: app.pop_screen()
        app._run("/hidden"); await pilot.pause()
        assert isinstance(app.screen, HiddenPicker)
        await pilot.press("u"); await pilot.pause()
    assert not b.found[0].get("user_hidden")


async def test_card_h_escape_goes_back_one_step(mk):
    from xbot.app import FilterOptions, PostCard
    b = mk(xonly=True, search=[P(10, text="Huge memecoin presale today"), P(11)], **S())
    b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app.action_show_post(1); await pilot.pause()
        await pilot.press("t"); await pilot.pause()
        assert isinstance(app.screen, FilterOptions)
        await pilot.press("space"); await pilot.press("escape"); await pilot.pause(); await pilot.pause()
        assert isinstance(app.screen, PostCard) and not b.found[0].get("user_hidden")
        await pilot.press("escape"); await pilot.pause()
        assert len(app.screen_stack) == 1
        assert "crypto-shill" not in b.cfg.filter_topics and not b.cfg.filter_words


def test_media_links_and_bracket_labels(mk):
    from xbot.xapi import attach_media, media_url
    from xbot.render import feed_text, card_renderable
    from rich.console import Console
    r = {"data": [{"id": "5", "text": "pic", "attachments": {"media_keys": ["3_1", "7_2"]}}, {"id": "6", "text": "none"}],
         "includes": {"media": [{"media_key": "3_1", "type": "photo", "url": "https://pbs.twimg.com/media/a.jpg"},
                                {"media_key": "7_2", "type": "video", "preview_image_url": "https://pbs.twimg.com/p.jpg",
                                 "variants": [{"content_type": "video/mp4", "bit_rate": 1, "url": "https://video.twimg.com/lo.mp4"},
                                              {"content_type": "video/mp4", "bit_rate": 9, "url": "https://video.twimg.com/hi.mp4"}]}]}}
    posts = attach_media(r)
    assert posts[0]["media"][1]["url"].endswith("hi.mp4") and "media" not in posts[1]
    assert media_url(posts[0]) == "https://pbs.twimg.com/media/a.jpg"
    assert media_url({"id": "9", "media": [{"type": "video", "url": None}]}) == "https://x.com/i/status/9/video/1"
    b = mk(xonly=True, search=[dict(posts[0], author_id="a", username="ua", conversation_id="5")], **S())
    opened = []; b.opener = lambda url, done: (opened.append(url), done("test"))
    b.tick()
    assert [f for f in b.feed if "pic" in f]
    assert b.found[0]["media"] and not hasattr(b, "open_media")  # media never goes to the browser
    b.open_profile(1); assert opened == ["https://x.com/ua"]
    rec = {"ts": "2026-10-24T08:00:00", "kind": "found", "n": 1, "source": "search", "author": "ua", "snippet": "pic",
           "tweet_id": "5", "media_url": "u"}
    t = feed_text(rec).plain
    assert "[media]" in t and "[post]" in t and "https://" not in t
    c = Console(width=110, record=True); c.print(card_renderable(1, b.found[0], b)); ct = c.export_text()
    assert "[post]" in ct and "[profile]" in ct and "[media]" in ct and "x.com/i/status" not in ct


async def test_approve_non_mention_opens_browser_with_hint(mk):
    b = mk(xonly=True, search=[P(10)], **S())
    opened = []; b.opener = lambda url, done: (opened.append(url), done("test"))
    b.tick(); b.handle(__import__("xbot.commands", fromlist=["parse"]).parse("/reply #1 cool"))
    app = XBotApp(bot=b, autostart=False)
    notes = []
    async with app.run_test(size=(140, 50)) as pilot:
        app.notify = lambda msg, **k: notes.append(msg)
        app.refresh_ui(); await pilot.pause()
        did = b.queue.pending()[0].id
        app._selected = lambda: did
        app.query_one("#queue").focus(); await pilot.pause()
        await pilot.press("a"); await pilot.pause()
    assert opened == ["https://x.com/intent/post?in_reply_to=10&text=cool"]  # hint NOT in the prefilled text
    assert any("add your own flavor" in n for n in notes) and b.dry_x.sent == []


async def test_mentioners_discoverable(mk):
    from rich.text import Text
    from xbot.render import feed_markup
    from xbot.app import MentionersEditor, PostCard
    base = {"kind": "filter", "ts": "2026-10-24T12:00:00", "msg": "", "on": True, "topics_on": [], "topics_off": [],
            "words": [], "tags": [], "skipped": []}
    empty = Text.from_markup(feed_markup(dict(base, mentioners=[]))).plain
    assert "(none yet: press q on a mention's card)" in empty and "edit list /mentioners" in empty
    b = mk(xonly=True, mentions=[{"id": "1", "text": "@me hi", "author_id": "m", "username": "pesky"}],
           search=[P(20)], **S())
    b.tick(); n = next(i for i, p in enumerate(b.found, 1) if p["id"] == "1")
    ns = next(i for i, p in enumerate(b.found, 1) if p["id"] == "20")
    b.queue.add("reply", "hey", in_reply_to="1", source="mention")
    app = XBotApp(bot=b, autostart=False)
    notes = []
    async with app.run_test(size=(140, 50)) as pilot:
        app.notify = lambda msg, **k: notes.append(msg)
        sub = app.query_one("#drafts").border_subtitle
        assert "m mentioners" in sub and "q" not in sub.replace("approve", "")
        assert "q" not in {b_.key for b_ in app.BINDINGS if not isinstance(b_, tuple)} | {t[0] for t in app.BINDINGS if isinstance(t, tuple)}
        app.query_one("#queue").focus(); await pilot.pause()
        await pilot.press("q"); await pilot.pause()
        assert b.cfg.filtered_mentioners == []  # q does nothing on the main screen
        app.action_show_post(ns); await pilot.pause()
        await pilot.press("q"); await pilot.pause()
        assert b.cfg.filtered_mentioners == []  # non-mention card: nothing
        await pilot.press("escape"); await pilot.pause()
        app.action_show_post(n); await pilot.pause()
        assert isinstance(app.screen, PostCard)
        await pilot.press("q"); await pilot.pause()
        assert b.cfg.filtered_mentioners == ["pesky"] and b.queue.pending() == []
        assert any("m or /mentioners" in x for x in notes)
        await pilot.press("escape"); await pilot.pause()
        app.query_one("#queue").focus(); await pilot.pause()
        await pilot.press("m"); await pilot.pause()
        assert isinstance(app.screen, MentionersEditor)


async def test_f2_opens_filter_view(mk):
    b = mk(xonly=True)
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app.query_one("#cmd").focus(); await pilot.pause()
        await pilot.press("f2"); await pilot.pause()
    assert '"kind": "filter"' in (b.log.dir / "actions.jsonl").read_text()
