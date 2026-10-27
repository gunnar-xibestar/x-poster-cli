"""Tests for the Oct 2026 plan: 429 back-off, queue size 4, hide forever, media detection, models, TUI polish."""
import json
import pytest
from xbot.commands import parse
from xbot.config import Config
from xbot.llm import FakeLLM, LLMRateLimited, SUPPORTED_MODELS, _msg
from xbot.xapi import attach_media, media_url
from test_search import P, S


class RateLLM(FakeLLM):
    def __init__(self, fails):
        super().__init__(["ok"] * 50)
        self.fails = fails

    def complete(self, system, user):
        self.calls.append(user)
        if self.fails:
            self.fails -= 1
            raise LLMRateLimited("xAI 429: too many requests for this API key", 60)
        return "ok"


def test_429_backs_off_one_warning_then_retries(mk):
    now = [1000.0]
    llm = RateLLM(1)
    b = mk(llm, search=[P(i) for i in range(1, 6)], clock=lambda: now[0], **S(max_replies_per_hour=100))
    b.tick()
    warns = [f for f in b.feed if "429" in f]
    assert len(warns) == 1 and len(llm.calls) == 1  # stopped after the first 429, one short message
    assert "\n" not in warns[0] and "llm_rpm=0" in warns[0] and "xbot config llm_rpm N" in warns[0] and "default 2" not in warns[0]
    assert b.rate_limited() == 60 and not b.retry_due() and b.queue.pending() == []
    assert b.draft_for_post(1) is None and "retrying in" in b.last_draft_error and len(llm.calls) == 1
    now[0] += 61
    assert b.retry_due()
    assert b.refill_from_catalog() == 4 and len(b.queue.pending()) == 4  # queue size 4
    assert not b.retry_due()


def test_msg_is_one_readable_line():
    from xbot.llm import _retry_after
    class E:
        body = {"error": {"message": "Too   many requests\nfor API key " + "x" * 400}}
        message = "m"
        class response:
            headers = {"retry-after": "30"}
    m = _msg(E())
    assert m.startswith("Too many requests for API key") and "\n" not in m and len(m) == 300
    assert _retry_after(E()) == 30 and _retry_after(object()) == 60


def test_429_maps_to_rate_limited():
    httpx = pytest.importorskip("httpx"); openai = pytest.importorskip("openai")
    from xbot.llm import GrokLLM
    req = httpx.Request("POST", "http://x/v1/chat/completions")
    resp = httpx.Response(429, request=req, headers={"retry-after": "30"})
    err = openai.RateLimitError("rl", response=resp, body={"error": {"message": "Too   many requests\nfor API key"}})
    assert _msg(err) == "Too many requests for API key"
    g = GrokLLM.__new__(GrokLLM); g.model = "grok-4.6"
    class C:
        class chat:
            class completions:
                @staticmethod
                def create(**kw): raise err
        base_url = "x"
    g.client = C
    with pytest.raises(LLMRateLimited) as e:
        g.complete("s", "u")
    assert e.value.retry_after == 30


def test_models_and_chat_only_endpoint(mk):
    assert SUPPORTED_MODELS == ("grok-4.7", "grok-4.6", "grok-4.5")
    import inspect, xbot.llm as L
    src = inspect.getsource(L.GrokLLM)
    assert "chat.completions.create" in src and "responses" not in src and "embeddings" not in src
    b = mk(FakeLLM())
    for m in SUPPORTED_MODELS:
        b.handle(parse(f"/model {m}")); assert b.cfg.model == m
    assert not any("not one of" in f for f in b.feed)
    b.handle(parse("/model grok-9")); assert any("not one of" in f for f in b.feed)


def test_queue_size_default_and_migration(tmp_path):
    assert Config().max_pending == 4 and Config().max_mention_drafts == 4
    (tmp_path / "config.json").write_text(json.dumps({"max_pending": 10, "max_mention_drafts": 7}))
    c = Config.load(tmp_path)
    assert c.max_pending == 4 and c.max_mention_drafts == 7 and c.queue_size_migrated
    (tmp_path / "config.json").write_text(json.dumps({"max_pending": 10, "queue_size_migrated": True}))
    assert Config.load(tmp_path).max_pending == 10  # configurable after migration


def test_hide_forever_removes_from_feed_and_queue_and_persists(mk, tmp_path):
    b = mk(FakeLLM(["hi"] * 20), search=[P(i) for i in range(1, 5)], **S(max_replies_per_hour=100))
    b.tick()
    assert len(b.queue.pending()) == 4
    b.found.append(dict(b.found[0], source="mention"))  # same post twice
    b.hide_post(1, forever=True)
    assert all(p.get("user_hidden") for p in b.found if p["id"] == "1")
    assert "1" not in {d.in_reply_to for d in b.queue.pending()}
    assert "1" not in {p["id"] for p in b.search_catalog() + b.mentions_waiting()}
    b.export()
    b2 = mk(FakeLLM())  # restart, same state dir
    assert "1" not in {p["id"] for p in b2.found}
    assert b2.nav_order()[0] == 1 and b2.found[0]["id"] != "1"  # numbering starts at #1


def test_startup_numbering_visible_first(mk):
    b = mk(xonly=True, search=[P(i) for i in range(1, 4)], **S())
    b.tick()
    b.hide_post(1, forever=False, why=["test"])
    b.export()
    b2 = mk(xonly=True)
    assert b2.nav_order() == [1, 2] and b2.found[2]["id"] == "1"


def test_media_detection_variants():
    resp = {"data": [
        {"id": "124", "text": "a", "attachments": {"media_keys": ["3_1"]}},
        {"id": "125", "text": "b", "entities": {"urls": [{"expanded_url": "https://x.com/EvikNova/status/125/photo/1",
                                                       "display_url": "pic.x.com/abc"}]}},
        {"id": "126", "text": "c", "referenced_tweets": [{"type": "quoted", "id": "900"}]},
        {"id": "127", "text": "d", "entities": {"urls": [{"media_key": "7_2", "expanded_url": "https://x.com/u/status/127/video/1"}]}},
        {"id": "128", "text": "plain", "entities": {"urls": [{"expanded_url": "https://example.com"}]}},
    ], "includes": {
        "media": [{"media_key": "3_1", "type": "photo", "url": "https://pbs.twimg.com/a.jpg"},
                  {"media_key": "3_9", "type": "photo", "url": "https://pbs.twimg.com/q.jpg"},
                  {"media_key": "7_2", "type": "video", "variants": [{"content_type": "video/mp4", "url": "https://v/1.mp4", "bit_rate": 1}]}],
        "tweets": [{"id": "900", "text": "quoted", "attachments": {"media_keys": ["3_9"]}}]}}
    ps = {p["id"]: p for p in attach_media(resp)}
    assert media_url(ps["124"]) == "https://pbs.twimg.com/a.jpg"
    assert media_url(ps["125"]) == "https://x.com/i/status/125/photo/1"
    assert media_url(ps["126"]) == "https://pbs.twimg.com/q.jpg"
    assert media_url(ps["127"]) == "https://v/1.mp4"
    assert "media" not in ps["128"]


def test_card_shows_v_when_media(mk):
    from rich.console import Console
    from xbot.render import card_renderable
    b = mk(xonly=True, search=[P(10)], **S())
    b.tick(); b.found[0]["media"] = [{"type": "photo", "url": None}]
    c = Console(width=120, record=True); c.print(card_renderable(1, b.found[0], b)); t = c.export_text()
    assert "view media" in t and "preview" not in t and "esc to back" in t


def test_edge_notify_throttled():
    from xbot.app import XBotApp
    app = XBotApp(bot=None, autostart=False)
    sent = []
    app.notify = lambda m, **k: sent.append(m)
    assert app.edge_notify("last post", now=100.0)
    for i in range(50):
        app.edge_notify("last post", now=100.0 + i * 0.1)
    assert sent == ["last post"]
    assert app.edge_notify("first post", now=110.5) and len(sent) == 2


async def test_h_hides_at_once_with_toast(mk):
    from xbot.app import XBotApp, PostCard
    b = mk(xonly=True, search=[P(10), P(11)], **S()); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        app.action_show_post(1); await pilot.pause()
        await pilot.press("h"); await pilot.pause(); await pilot.pause()
        assert b.found[0].get("user_hidden") == "forever"
        assert any("#1 hidden for good" in str(n.message) for n in app._notifications)


async def test_edit_in_place_and_queue_click_opens_card(mk):
    from textual.widgets import Input, ListView
    from xbot.app import XBotApp, PostCard, FoundPicker
    b = mk(FakeLLM(["hi"] * 10), search=[P(10), P(11)], **S(max_replies_per_hour=100)); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        lv = app.query_one("#queue", ListView); lv.focus(); lv.index = 1; await pilot.pause()
        did = app._selected()
        await pilot.press("e"); await pilot.pause()
        inp = app.query_one("#qedit", Input)
        assert inp.has_focus and inp.parent is lv.highlighted_child
        assert not any(isinstance(s, FoundPicker) for s in app.screen_stack)
        inp.value = "edited text"
        await pilot.press("enter"); await pilot.pause(); await pilot.pause()
        assert b.queue.get(did).text == "edited text" and not app.query("#qedit")
        assert app.query_one("#cmd", Input).value == ""
        lv = app.query_one("#queue", ListView); lv.focus(); lv.index = 1; await pilot.pause()
        await pilot.press("enter"); await pilot.pause()
        assert isinstance(app.screen, PostCard) and app.screen.n == app.post_number_for_draft(did)


async def test_found_picker_esc_one_step(mk):
    from xbot.app import XBotApp, PostCard, FoundPicker
    b = mk(xonly=True, search=[P(10), P(11)], **S()); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 50)) as pilot:
        await pilot.pause()
        app.query_one("#queue").focus()
        await pilot.press("f"); await pilot.pause()
        assert isinstance(app.screen, FoundPicker)
        await pilot.press("enter"); await pilot.pause()
        assert isinstance(app.screen, PostCard)
        await pilot.press("escape"); await pilot.pause()
        assert isinstance(app.screen, FoundPicker)
        await pilot.press("escape"); await pilot.pause()
        assert len(app.screen_stack) == 1
