import threading, time
from xbot.video import PostActions, StatusPainter, next_post_index, controls_line, KeyReader, parse_keys

def items():
    return [dict(kind="photo", url="a", n=1, post_id="1", post_idx=1, post_count=3, sub=1, sub_count=2, handle="x"),
            dict(kind="photo", url="b", n=1, post_id="1", post_idx=1, post_count=3, sub=2, sub_count=2, handle="x"),
            dict(kind="video", url="c", n=2, post_id="2", post_idx=2, post_count=3, sub=1, sub_count=1, handle="y"),
            dict(kind="video", url="d", n=3, post_id="3", post_idx=3, post_count=3, sub=1, sub_count=1, handle="z")]


def mk(start=0, **kw):
    p = StatusPainter(items(), 200, 40, write=lambda s: None, start=start)
    sent, logs = [], []
    pa = PostActions(p, sent.append, log=logs.append, **kw)
    return p, pa, sent, logs


def test_r_t_digits_are_parsed_keys():
    assert parse_keys(b"rRtT")[0] == ["r", "R", "t", "T"]


def test_next_post_index():
    its = items()
    assert next_post_index(its, 0) == 2 and next_post_index(its, 3) is None


def test_remove_advances_in_place_and_logs():
    done = threading.Event()
    p, pa, sent, logs = mk(remove=lambda it: done.set() or "@x muted, post hidden", run=lambda f: f())
    assert pa.key("r") is True
    assert sent[0] == ["playlist-play-index", 2]
    assert sent[1:] == [["playlist-remove", 1], ["playlist-remove", 0]]  # in place: mpv is not restarted
    assert [i["post_id"] for i in p.items] == ["2", "3", ] and p.pos() == 0 and p.current()["n"] == 2
    assert done.is_set() and "✓ @x muted" in p.msg
    assert any("requested" in l for l in logs) and any("playlist" in l for l in logs) and any("muted" in l for l in logs)
    assert ["quit"] not in sent  # more posts left: the viewer stays open


def test_slow_or_blocking_mute_does_not_hold_the_viewer():
    gate = threading.Event()
    p, pa, sent, logs = mk(remove=lambda it: gate.wait(5) and "late", timeout=0.2)
    t0 = time.monotonic()
    assert pa.key("r") is True
    assert time.monotonic() - t0 < 0.1  # key thread returns at once
    assert sent[0] == ["playlist-play-index", 2] and p.current()["n"] == 2  # already advanced
    assert pa.key("d") is False  # other keys still flow to mpv
    time.sleep(0.5)
    assert "pending" in p.msg and any("still running" in l for l in logs)
    gate.set()


def test_remove_failure_reported():
    def boom(it): raise RuntimeError("x down")
    p, pa, sent, logs = mk(remove=boom, run=lambda f: f())
    pa.key("r")
    assert "failed" in p.msg and any("failed" in l for l in logs)


def test_remove_middle_post_and_last_post():
    p, pa, sent, _ = mk(start=3, remove=lambda it: "ok", run=lambda f: f())
    pa.key("r")  # last post: goes back to previous post
    assert sent[0] == ["playlist-play-index", 2] and p.current()["n"] == 2 and len(p.items) == 3


def test_t_requests_popup_and_quits_mpv():
    req = []
    p, pa, sent, _ = mk(start=1, popup=lambda it, pos: req.append((it["n"], it["sub"], pos)))
    assert pa.key("t") is True
    assert req == [(1, 2, 1)] and sent == [["quit"]]


def test_other_keys_pass_through_and_hint():
    p, pa, *_ = mk(remove=lambda it: "x")
    assert pa.key("l") is False
    assert "r remove  t tags" in controls_line("photo", item=items()[0])


def test_keyreader_intercept():
    sent = []
    kr = KeyReader(0, sent.append, intercept=lambda k: k == "r")
    kr.forward("r"); kr.forward("d")
    assert sent == [["keypress", "d"]]


def test_popup_handoff_cancel_and_apply():
    from types import SimpleNamespace
    from xbot.app import XBotApp, FilterOptions
    calls, screens = [], []
    class Log:
        def event(self, *a, **k): pass
    posts = {1: {"media": [1]}, 2: {}, 3: {"media": [1]}}
    bot = SimpleNamespace(log=Log(), nav_order=lambda: [1, 2, 3], found_post=lambda k: posts[k])
    fake = SimpleNamespace(bot=bot, push_screen=lambda s, cb: screens.append((s, cb)),
                           play_media=None,
                           _reopen_viewer=lambda n, which, run, sub, origin=None: calls.append((n, sub)), resync_after_hide=lambda *a, **k: None,
                           refresh_ui=lambda: None, apply_filters_and_refill=lambda: None, notify=lambda *a, **k: None)
    XBotApp._viewer_popup(fake, {"n": 1, "sub": 2})
    s, cb = screens[-1]
    assert isinstance(s, FilterOptions) and s.n == 1
    cb("cancel"); assert calls[-1] == (1, 2)  # Esc: same item
    cb(True); assert calls[-1] == (3, 1)  # applied: next post WITH media (2 has none)


def test_reopen_after_popup_is_deferred_not_inside_callback():
    from types import SimpleNamespace
    from xbot.app import XBotApp
    timers, played = [], []
    fake = SimpleNamespace(set_timer=lambda d, f: timers.append((d, f)),
                           play_media=lambda n, **k: played.append((n, k["start_sub"])))
    XBotApp._reopen_viewer(fake, 7, None, None, 2)
    assert played == [] and timers and timers[0][0] > 0  # not run inside the dismiss callback
    timers[0][1](); assert played == [(7, 2)]


def test_a_d_do_nothing_on_photos_but_seek_videos():
    p, pa, sent, _ = mk()
    assert pa.key("a") is True and pa.key("d") is True and sent == []  # photo: swallowed
    p.update("playlist-pos", 2)  # video
    assert pa.key("a") is False and pa.key("d") is False  # forwarded -> mpv seeks


def test_video_hint_order():
    v = controls_line("video", item=items()[2])
    assert "a/d seek 5s  ·  ↑/↓ volume  ·  space pause  ·  m mute  ·  ←/→ prev/next" in v
    assert "←/→ prev/next" in controls_line("photo", item=items()[0]) and "seek" not in controls_line("photo", item=items()[0])


def test_arrows_vs_lone_esc_on_raw_tty():
    import os
    r, w = os.pipe()
    sent = []
    kr = KeyReader(r, sent.append); kr.thread.start()
    os.write(w, b"\x1b[C"); time.sleep(0.15)
    os.write(w, b"\x1bOD"); time.sleep(0.15)
    os.write(w, b"\x1b"); time.sleep(0.3)
    os.close(w); kr.stop(); os.close(r)
    assert sent == [["keypress", "RIGHT"], ["keypress", "LEFT"], ["keypress", "ESC"]]


def test_r_on_only_post_with_media_hides_then_closes_viewer():
    one = [dict(kind="video", url="c", n=2, post_id="2", post_idx=1, post_count=1, sub=1, sub_count=1, handle="y")]
    p = StatusPainter(one, 200, 40, write=lambda s: None)
    sent, logs, removed = [], [], []
    pa = PostActions(p, sent.append, log=logs.append, remove=lambda it: removed.append(it["n"]) or "@y muted, post hidden",
                     run=lambda f: f())
    assert pa.key("r") is True
    assert removed == [2] and sent[-1] == ["quit"]  # quit only after the hide ran
    assert not any(c[0] == "playlist-play-index" for c in sent)
    assert any("closing the viewer" in l for l in logs)


async def test_r_on_only_media_post_returns_to_search_view(mk, monkeypatch):
    import contextlib
    from xbot import video
    from xbot.app import XBotApp, PostCard
    from tests.test_search import P, S
    b = mk(xonly=True, search=[P(5, author="a1"), P(6, author="a2"), P(7, author="a3")], **S()); b.tick()
    for p, h in zip(b.found, ("ann", "bob", "cy")):
        p["username"] = h
    b.found[1]["media"] = [{"type": "video", "url": "https://video.twimg.com/v.mp4"}]
    monkeypatch.setattr(b, "media_items", lambda n: b.found_post(n).get("media") or [], raising=False)
    def fake_run(url, cfg, run=None, which=None, **k):  # the viewer: real PostActions, r on the only post
        items = video.posts_playlist(k["posts"])
        assert len(items) == 1
        p = video.StatusPainter(items, 200, 40, write=lambda s: None)
        sent = []
        acts = k["actions"]
        video.PostActions(p, sent.append, run=lambda f: f(), **acts).key("r")
        assert sent[-1] == ["quit"]
        k["state"]["last"] = {"n": items[0]["n"]}
        return "mpv"
    monkeypatch.setattr(video, "run_mpv", fake_run)
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/mpv" if n == "mpv" else None)
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 40)) as pilot:
        app.query_one("#queue").focus()
        await pilot.press("f"); await pilot.pause()
        app.action_show_post(2); await pilot.pause()
        app.screen
        monkeypatch.setattr(app, "suspend", lambda: contextlib.nullcontext())
        await pilot.press("v"); await pilot.pause(); await pilot.pause()
        assert b.nav_order() == [1, 3]  # only the removed post is hidden
        assert isinstance(app.screen, PostCard) and app.screen.n != 2  # back in the search view, rebuilt
        b.stopped = True
