import json
from textual.widgets import SelectionList
from xbot.commands import parse
from xbot.tags import tag_text, tag_post, build_query, DEFAULT_TAXONOMY
from xbot.app import XBotApp, TagPicker
from tests.test_search import P, S


def test_tagger_keywords_hashtags_annotations():
    assert tag_text("New #Rust release, cargo is fast") == ["rust"]
    assert tag_text("Bitcoin and $ETH pumping") == ["crypto"]
    assert set(tag_text("Fine-tuning an LLM on Linux with PyTorch")) == {"ai", "linux", "python"}
    assert tag_text("trusted rusty pythonic") == []  # word boundaries
    p = {"text": "big news today", "context_annotations": [
        {"domain": {"name": "Cryptocurrencies"}, "entity": {"name": "Dogecoin"}},
        {"domain": {"name": "Brand"}, "entity": {"name": "Kubernetes"}}]}
    assert tag_post(p) == ["crypto", "devops"]


def test_build_query_respects_limit():
    q, added, dropped = build_query("linux", ["crypto"], limit=512)
    assert '-bitcoin' in q and added == len(DEFAULT_TAXONOMY["crypto"]) and dropped == 0
    q2, a2, d2 = build_query("x" * 500, ["crypto", "jobs"], limit=512)
    assert len(q2) <= 512 and d2 > 0
    assert build_query("ai", [], limit=512)[0] == "ai"
    assert '-"open source"' in build_query("q", ["opensource"])[0]


def test_found_tagged_shown_and_exported(mk):
    b = mk(xonly=True, search=[P(1, text="Rust 2.0 + cargo"), P(2, text="buy bitcoin now")], **S())
    b.tick()
    assert b.found[0]["tags"] == ["rust"] and any("#rust" in f or "{rust}" in f for f in b.feed)
    assert json.loads(b.found_path.read_text())["posts"][1]["tags"] == ["crypto"]


def test_exclude_hides_search_never_mentions_and_adds_query_terms(mk):
    b = mk(xonly=True, mentions=[{"id": "1", "text": "@me bitcoin?", "author_id": "m"}],
           search=[P(10, text="bitcoin moon"), P(11, text="linux kernel 7")], **S())
    b.handle(parse("/exclude crypto"))
    assert b.cfg.excluded_tags == ["crypto"]
    b.tick()
    assert "-bitcoin" in b.dry_x.searches[-1]
    assert [p["id"] for p in b.found] == ["1", "11"]  # mention kept, crypto search post dropped
    assert any("1 hidden by filter" in f for f in b.feed)
    b.dry_x.fake_search = [P(12, text="eth gas")]; b.tick()  # previously found crypto posts get hidden too
    b.handle(parse("/include crypto")); assert b.cfg.excluded_tags == []
    b.found.append({"id": "99", "text": "nft drop", "source": "search", "tags": ["crypto"]})
    b.handle(parse("/exclude crypto")); assert all(p["id"] != "99" for _, p in b.visible_found())
    b.feed.clear(); b.handle(parse("/found")); assert not any("…99" in f for f in b.feed)
    b.handle(parse("/excluded")); assert "x crypto" in b.feed[-1]


def test_exclude_unknown_tag_and_posttopics(mk):
    b = mk()
    import pytest
    with pytest.raises(KeyError): b.handle(parse("/exclude nonsense"))
    b.handle(parse("/posttopics a, b")); assert b.cfg.topics == ["a", "b"]


async def test_tag_picker_modal(mk):
    b = mk(xonly=True, search=[P(1, text="rust"), P(2, text="bitcoin")], **S()); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(120, 50)) as pilot:
        app._run("/topics"); await pilot.pause()
        assert isinstance(app.screen, TagPicker)
        sl = app.screen.query_one(SelectionList)
        idx = list(b.taxonomy).index("crypto")
        sl.focus(); sl.highlighted = idx; await pilot.pause()
        await pilot.press("space"); await pilot.pause()
        await pilot.press("enter"); await pilot.pause()
        assert not isinstance(app.screen, TagPicker) and b.cfg.excluded_tags == ["crypto"]


async def test_card_t_picker_excludes_that_posts_tags(mk):
    from textual.widgets import SelectionList
    from xbot.app import FilterOptions
    b = mk(xonly=True, search=[P(1, text="bitcoin on linux"), P(2, text="rust")], **S()); b.tick()
    b.cfg.excluded_tags = ["rust"]
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(120, 50)) as pilot:
        app.action_show_post(1); await pilot.pause()
        await pilot.press("t"); await pilot.pause()
        assert isinstance(app.screen, FilterOptions)
        vals = [v for v, _ in b.filter_options(b.found[0])]
        assert "tag:crypto" in vals and "tag:linux" in vals and "tag:rust" not in vals and vals[0].startswith("author:")
        app.screen.query_one(SelectionList).select("tag:crypto")
        await pilot.press("enter"); await pilot.pause()
        assert b.cfg.excluded_tags == ["crypto", "rust"] and b.found[0].get("user_hidden")


async def test_card_t_no_tags(mk):
    b = mk(xonly=True, search=[P(1, text="hello world")], **S()); b.tick()
    assert not [v for v, _ in b.filter_options(b.found[0]) if v.startswith("tag:")]

