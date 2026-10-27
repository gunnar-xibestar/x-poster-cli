from xbot.commands import parse
from xbot.safety import reasons
from tests.test_search import P, S


def test_reasons_topics_and_words():
    assert reasons({"text": "BREAKING: missiles hit the port overnight"}, ("war",)) == ["war"]
    assert reasons({"text": "BREAKING: Linux 7.0 released"}, ("war",)) == []
    assert reasons({"text": "Big tech layoffs again"}, (), ["layoffs"]) == ['word:"layoffs"']
    assert reasons({"text": "warp drive"}, ("war",)) == []


def test_filter_command_hides_war_news_not_all_news(mk):
    b = mk(xonly=True, search=[P(1, text="BREAKING: airstrike on city, AI drones used"),
                               P(2, text="BREAKING: new AI model ships"),
                               P(3, text="AI layoffs hit big tech")], **S())
    b.tick()
    assert len(b.visible_found()) == 3
    b.handle(parse("/filter hide war layoffs"))
    assert "war" in b.cfg.filter_topics and b.cfg.filter_words == ["layoffs"]
    assert [p["id"] for _, p in b.visible_found()] == ["2"]
    assert " -layoffs" in b.effective_query()[0]
    b.handle(parse("/filter why 1")); assert "war" in b.feed[-1]
    b.handle(parse("/filter show layoffs")); assert len(b.visible_found()) == 2
    b.handle(parse("/filter off")); assert len(b.visible_found()) == 3
    b.handle(parse("/filter")); assert "filter off" in b.feed[-1]


def test_hidden_list_reasons_and_blocked_excluded(mk):
    b = mk(xonly=True, search=[P(1, text="BREAKING: airstrike on city"), P(2, text="Join my telegram now"),
                               P(3, text="Linux tip", author="baddie"), P(4, text="Rust tip")], **S())
    b.cfg.filter_topics = ["adult", "spam", "war"]; b.cfg.blocked_authors = ["baddie"]
    for p in b.dry_x.fake_search: p["username"] = p["author_id"]
    b.tick()
    assert any("2 hidden by filter" in f for f in b.feed)
    items = b.hidden_list()
    assert [(l, w) for l, _, w in items] == [("h1", ['topic war ("airstrike")']), ("h2", ['spam ("Join my telegram")'])]
    b.handle(parse("/hidden"))
    assert any('caught by: topic war ("airstrike")' in f for f in b.feed) and not any("baddie" in f and "why" in f for f in b.feed)
    assert b.filtered_path.exists()


def test_hidden_recent_vs_all(mk):
    b = mk(xonly=True, search=[P(1, text="Join my telegram now")], **S()); b.tick()
    b.dry_x.fake_search[:] = [P(2, text="BREAKING: airstrike on city")]
    b.cfg.filter_topics = ["adult", "spam", "war"]; b.search_since_id = None; b.tick()
    b.handle(parse("/hidden")); recent = [f for f in b.feed if "caught by:" in f]
    assert len(recent) == 1 and "war" in recent[0]
    b.feed.clear(); b.handle(parse("/hidden all"))
    assert len([f for f in b.feed if "caught by:" in f]) == 2


def test_edit_topic_words(mk):
    from xbot.safety import reasons, set_topic_edits
    b = mk(xonly=True, search=[], **S())
    b.handle(parse("/filter edit war +drone -russia"))
    assert b.cfg.topic_edits == {"war": {"add": ["drone"], "remove": ["russia"]}}
    assert reasons({"text": "new drone sdk"}, ("war",)) == ["war"]
    assert reasons({"text": "russia tech news"}, ("war",)) == []
    b.handle(parse("/filter reset war")); assert b.cfg.topic_edits == {}
    assert reasons({"text": "russia tech news"}, ("war",)) == ["war"]
    set_topic_edits({})


def test_edit_adult_and_set_words(mk):
    from xbot.safety import flags, set_topic_edits
    b = mk(xonly=True, search=[], **S())
    b.handle(parse("/filter edit adult -sexy +lewd"))
    assert flags({"text": "so lewd"}) == ["adult"] and flags({"text": "sexy code"}) == []
    b.set_topic_words("spam", ["click here"])
    assert flags({"text": "giveaway now"}) == [] and flags({"text": "click here"}) == ["spam"]
    set_topic_edits({})


async def test_topic_picker_screens(mk):
    from xbot.app import XBotApp, TopicPicker, TopicWords
    from xbot.safety import flags, set_topic_edits
    b = mk(xonly=True, search=[], **S())
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app._run("/filter edit"); await pilot.pause()
        assert isinstance(app.screen, TopicPicker)
        await pilot.press("e"); await pilot.pause()
        assert isinstance(app.screen, TopicWords) and app.screen.topic == "adult"
        await pilot.press("tab"); await pilot.press(*"lewd", "enter"); await pilot.pause()
        await pilot.press("ctrl+s"); await pilot.pause()
        assert isinstance(app.screen, TopicPicker) and "lewd" in b.cfg.topic_edits["adult"]["add"]
        await pilot.press("down", "down", "down", "space", "enter"); await pilot.pause()
        assert "war" in b.cfg.filter_topics
        app._run("/filter edit spam"); await pilot.pause()
        assert isinstance(app.screen, TopicWords) and app.screen.topic == "spam"
    assert flags({"text": "so lewd"}) == ["adult"]
    set_topic_edits({})


async def test_topic_picker_r_refills(mk):
    from xbot.app import XBotApp, TopicPicker
    b = mk(xonly=True, search=[], **S())
    app = XBotApp(bot=b, autostart=False)
    calls = []
    b.tick = lambda force=False: calls.append(force) or 0
    async with app.run_test(size=(140, 50)) as pilot:
        app._run("/filter edit"); await pilot.pause()
        assert isinstance(app.screen, TopicPicker)
        await pilot.press("r"); await pilot.pause(); await pilot.pause()
        assert not isinstance(app.screen, TopicPicker) and calls == [True]


async def test_hidden_popup(mk):
    from xbot.app import XBotApp, HiddenPicker
    b = mk(xonly=True, search=[], **S())
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app._run("/hidden"); await pilot.pause()
        assert isinstance(app.screen, HiddenPicker) and not app.screen.all_
        await pilot.press("a"); await pilot.pause(); assert app.screen.all_
        await pilot.press("escape"); await pilot.pause()
        assert not isinstance(app.screen, HiddenPicker)


def test_show_subword_removes_from_topic(mk):
    from xbot.safety import flags, set_topic_edits
    b = mk(xonly=True, search=[], **S())
    assert flags({"text": "my Fansly page"}) == ["adult"]
    b.handle(parse('/filter show "Fansly"'))
    assert b.cfg.topic_edits["adult"]["remove"] == ["fansly"] and flags({"text": "my Fansly page"}) == []
    set_topic_edits({})


def test_mentions_outside_queue_cap():
    from xbot.queue import DraftQueue
    import tempfile, pathlib
    q = DraftQueue(pathlib.Path(tempfile.mkdtemp()) / "q.json")
    q.add("reply", "s1", in_reply_to="1", source="search")
    q.add("reply", "m1", in_reply_to="2", source="mention")
    assert [d.text for d in q.pending()] == ["m1", "s1"] and [d.text for d in q.pending_capped()] == ["s1"]


def test_filter_mentioner(mk):
    m = [{"id": "1", "text": "@me hi", "author_id": "a", "username": "Pest"},
         {"id": "2", "text": "@me yo", "author_id": "b", "username": "pal"}]
    b = mk(xonly=True, mentions=m, search=[], **S()); b.tick()
    assert [p["username"] for p in b.found if p["source"] == "mention"] == ["Pest", "pal"]
    d = b.queue.add("reply", "thanks", in_reply_to="1", source="mention")
    b.filter_mentioner(d.id)
    assert b.cfg.filtered_mentioners == ["pest"] and not b.queue.pending()
    b.handle(parse("/filter show @pest")); assert b.cfg.filtered_mentioners == []
