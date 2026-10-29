"""v = every photo/video/GIF of a post in the terminal mpv viewer (A/D browse); no i panel, no V, no browser."""
import contextlib, json, socket, threading
from xbot import video
from xbot.app import XBotApp, PostCard, search_cli
from xbot.config import Config
from tests.test_search import S
from tests.test_media_layout import P

MIXED = [{"type": "photo", "url": "https://pbs.twimg.com/media/a.jpg"},
         {"type": "video", "url": "https://video.twimg.com/v.mp4",
          "variants": [{"content_type": "video/mp4", "bit_rate": 9, "url": "https://video.twimg.com/vid/640x360/v.mp4"}]},
         {"type": "animated_gif", "url": "https://video.twimg.com/g.mp4"},
         {"type": "photo", "url": "https://pbs.twimg.com/media/b.png"}]


def test_playlist_and_mpv_argv_for_mixed_post():
    items = video.playlist(MIXED, max_h=800)
    assert [i["kind"] for i in items] == ["photo", "video", "video", "photo"]
    assert items[0]["url"] == "https://pbs.twimg.com/media/a?format=jpg&name=large"
    assert items[1]["url"].endswith("640x360/v.mp4")
    a = video.mpv_argv(items, "tct", "off", 100, 30, input_fd=7, ipc_fd=9)
    assert a[a.index("--") + 1:] == [i["url"] for i in items]  # one playlist, in post order
    assert "--image-display-duration=inf" in a and "--keep-open=no" in a
    assert "--osd-level=0" in a and "--osd-bar=no" in a and "--term-osd=no" in a  # nothing drawn on the frame
    assert not any(x.startswith("--osd-status-msg") for x in a)
    assert "--vo-tct-height=28" in a  # 30 rows - 2 reserved for the controls line
    s = video.mpv_argv(items, "sixel", "off", 100, 30)
    assert "--vo-sixel-rows=26" in s and "--vo-sixel-top=1" in s  # picture ends above the reserved rows
    conf = dict(l.split(" ", 1) for l in video.INPUT_CONF.strip().splitlines())
    assert conf["LEFT"] == "playlist-prev; script-message xbot-prev" and conf["RIGHT"] == "playlist-next; script-message xbot-next"
    assert conf["a"] == conf["A"] == "seek -5" and conf["d"] == conf["D"] == "seek 5" and conf["UP"] == "add volume 5"
    assert conf["DOWN"] == "add volume -5" and conf["SPACE"] == "cycle pause" and conf["m"] == "cycle mute"
    assert conf["q"] == conf["ESC"] == "quit" and "l script-message xbot-like" in video.LIKE_CONF


def test_controls_line_photo_vs_video():
    ph = video.controls_line("photo", 1, 4)
    assert ph.startswith("2/4") and "←/→ prev/next" in ph and "l like" in ph and "q/Esc back" in ph
    for k in ("seek", "volume", "pause", "mute"):
        assert k not in ph
    vd = video.controls_line("video", 2, 4, {"time-pos": 65, "duration": 120, "pause": True, "mute": True})
    assert vd.startswith("3/4") and "1:05/2:00 PAUSED muted" in vd
    for k in ("a/d seek 5s", "↑/↓ volume", "space pause", "m mute", "←/→ prev/next", "l like", "q/Esc back"):
        assert k in vd
    assert "←/→ prev/next" in video.controls_line("photo", 0, 1)  # always shown, even with one item
    assert "♥ liked" in video.controls_line("photo", 0, 1, liked=True)
    assert len(video.controls_line("video", 0, 4, width=40)) == 40


def test_painter_draws_below_picture_and_follows_playlist():
    out = []
    items = video.playlist(MIXED)
    p = video.StatusPainter(items, cols=100, rows=30, write=out.append)
    p.paint()
    assert "\x1b[29;1H" in out[-1] and "\x1b[30;1H" in out[-1] and "1/4" in out[-1] and "seek" not in out[-1]
    assert out[-1].startswith("\x1b7") and out[-1].endswith("\x1b8")  # cursor saved/restored around it
    p.update("playlist-pos", 1)
    assert "2/4" in out[-1] and "seek" in out[-1]


def test_ipc_loop_observes_paints_and_likes():
    ours, theirs = socket.socketpair()
    out, likes = [], []
    painter = video.StatusPainter(video.playlist(MIXED), 100, 30, write=out.append)
    t = threading.Thread(target=video.ipc_loop, args=(ours, lambda it: (likes.append(it), "liked #3")[1], 0),
                         kwargs={"painter": painter}, daemon=True)
    t.start()
    f = theirs.makefile("rb")
    cmds = [json.loads(f.readline())["command"] for _ in video.OBSERVE]
    assert [c[2] for c in cmds] == list(video.OBSERVE) and all(c[0] == "observe_property" for c in cmds)
    theirs.sendall(b'{"event":"property-change","name":"playlist-pos","data":3}\n'
                   b'{"event":"client-message","args":["xbot-like"]}\n')
    import time
    for _ in range(100):
        if likes and "liked #3" in out[-1]:
            break
        time.sleep(0.02)
    theirs.shutdown(socket.SHUT_RDWR); theirs.close(); t.join(2)
    assert likes == [painter.items[3]] and "4/4" in out[-1] and "♥ liked #3" in out[-1]


async def test_v_on_photo_goes_to_mpv_not_browser(mk, monkeypatch):
    b = mk(xonly=True, search=[P(1, "pics")], **S()); b.tick()
    b.found[0]["media"] = [dict(m) for m in MIXED]
    b.video_forbidden = lambda url: False
    seen, opened, events = [], [], []
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/mpv" if n == "mpv" else None)
    monkeypatch.setattr(video, "run_mpv", lambda url, cfg, run=None, which=None, **k: (seen.append(k), events.append("mpv"))[0] or "mpv")
    app = XBotApp(bot=b, autostart=False)
    @contextlib.contextmanager
    def fake_suspend():
        events.append("suspend"); yield; events.append("resume")
    async with app.run_test(size=(120, 40)) as pilot:
        b.opener = lambda url, done: opened.append(url)
        app.suspend = fake_suspend
        app.action_show_post(1); await pilot.pause()
        card = app.screen
        await pilot.press("v"); await pilot.pause()
        assert events == ["suspend", "mpv", "resume"] and not opened
        assert seen[0]["start_n"] == 1 and [m["type"] for m in seen[0]["posts"][0][1]["media"]] == ["photo", "video", "animated_gif", "photo"]
        assert callable(seen[0]["on_like"]) and seen[0]["liked"]() is False
        assert app.screen is card and card.n == 1
        app.action_open_media(1); await pilot.pause(0.3)  # the clickable [media] label: same viewer
        assert len(seen) == 2 and not opened
        b.stopped = True


async def test_i_and_V_unbound_and_no_media_panel(mk, monkeypatch):
    b = mk(xonly=True, search=[P(1, "pic")], **S()); b.tick()
    b.found[0]["media"] = [{"type": "photo", "url": "https://pbs.twimg.com/a.jpg"}]
    keys = {(k if isinstance(k, str) else k.key) for bnd in PostCard.BINDINGS
            for k in [bnd[0] if isinstance(bnd, tuple) else bnd.key] for k in k.split(",")}
    assert "v" in keys and "i" not in keys and "V" not in keys
    assert not hasattr(PostCard, "action_preview") and not hasattr(PostCard, "action_media_external")
    played, opened = [], []
    monkeypatch.setattr(video, "run_mpv", lambda *a, **k: played.append(1))
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(120, 40)) as pilot:
        b.opener = lambda url, done: opened.append(url)
        app.action_show_post(1); await pilot.pause()
        card = app.screen
        assert not card.query("#media")  # card text gets the full space
        await pilot.press("i"); await pilot.pause(); await pilot.press("V"); await pilot.pause()
        assert isinstance(app.screen, PostCard) and not played and not opened
        b.stopped = True


async def test_missing_mpv_never_opens_browser(mk, monkeypatch):
    b = mk(xonly=True, search=[P(1, "clip")], **S()); b.tick()
    b.found[0]["media"] = [{"type": "video", "url": "https://video.twimg.com/v.mp4"}, {"type": "photo", "url": "https://pbs.twimg.com/a.jpg"}]
    monkeypatch.setattr("shutil.which", lambda n: None)
    opened, notes = [], []
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(120, 40)) as pilot:
        b.opener = lambda url, done: opened.append(url)
        app.notify = lambda m, **k: notes.append(m)
        app.action_show_post(1); await pilot.pause()
        await pilot.press("v"); await pilot.pause()
        app.action_open_media(1); await pilot.pause(0.3)
        assert not opened and any("mpv not found" in n for n in notes)
        b.stopped = True


async def test_suspend_failure_never_opens_browser(mk, monkeypatch):
    b = mk(xonly=True, search=[P(1, "clip")], **S()); b.tick()
    b.found[0]["media"] = [{"type": "photo", "url": "https://pbs.twimg.com/a.jpg"}]
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/mpv")
    opened = []
    app = XBotApp(bot=b, autostart=False)
    def bad():
        raise RuntimeError("no suspend")
    async with app.run_test(size=(120, 40)) as pilot:
        b.opener = lambda url, done: opened.append(url)
        app.suspend = bad
        app.action_show_post(1); await pilot.pause()
        assert app.play_media(1) == "failed" and not opened and app.is_running
        b.stopped = True


def test_run_mpv_playlist_reserves_rows_and_like(tmp_path):
    calls = []
    def run(argv, **k):
        calls.append((argv, k))
    assert video.run_mpv(None, Config(video_vo="tct"), run=run, which=lambda n: "/usr/bin/mpv", size=(90, 25), tty=None,
                         media=MIXED, on_like=lambda: "ok") == "mpv"
    argv, k = calls[0]
    assert "--vo-tct-height=23" in argv and argv[-4:][0].startswith("https://pbs.twimg.com/media/a")
    assert len(k["pass_fds"]) == 2 and any(x.startswith("--input-ipc-client=fd://") for x in argv)
    assert video.run_mpv(None, Config(), run=run, which=lambda n: "/usr/bin/mpv", size=(90, 25), tty=None,
                         media=[{"type": "photo", "url": None}]) == "empty"


def test_old_config_keys_ignored(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"video_player": "external", "preview_renderer": "sixel", "video_vo": "tct"}))
    c = Config.load(tmp_path)
    assert c.video_vo == "tct" and not c.load_warnings and not hasattr(c, "video_player")
    from xbot.configcli import cli
    out = []
    assert cli(["video_vo", "sixel"], config_dir=tmp_path, out=out.append) == 0
    assert "video_player" not in (tmp_path / "config.json").read_text()
    assert cli(["video_player", "mpv"], config_dir=tmp_path, out=out.append) == 2  # removed setting
    assert cli(["video_audio", "loud"], config_dir=tmp_path, out=out.append) == 2


def test_search_cli_play_all_media(monkeypatch):
    class X:
        def search_recent(self, q, n):
            return [{"id": "1", "text": "no media"}, {"id": "2", "text": "pics", "media": [dict(m) for m in MIXED]}]
    out, played = [], []
    monkeypatch.setattr(video, "url_forbidden", lambda u: False)
    cfg = Config()
    assert search_cli(["rust", "--play", "1"], x=X(), cfg=cfg, out=out.append,
                      play=lambda argv, **k: played.append(argv), which=lambda n: "/usr/bin/mpv") == 0
    mpv = played[0]
    assert len(mpv[mpv.index("--") + 1:]) == 4 and "--image-display-duration=inf" in mpv
    assert any("[media 1: 4 items, video]" in l for l in out)
    assert search_cli(["rust", "--play", "1"], x=X(), cfg=cfg, out=out.append, which=lambda n: None) == 1
    assert "mpv not found" in out[-1]
    assert search_cli(["rust", "--play", "5"], x=X(), cfg=cfg, out=out.append) == 2


def test_help_and_card_hints():
    from xbot import help as H
    txt = H.render_help()
    assert "←/→ previous/next item" in txt and "browser" not in [d for k, d in H.KEYS if k == "v (in card)"][0]
    assert not any(k.startswith(("i (in card)", "V (in card)")) for k, _ in H.KEYS)


async def test_click_media_and_v_give_identical_mpv_args(mk, monkeypatch):
    """[media] click and v must reach run_mpv with the same options and produce the same mpv argv."""
    b = mk(xonly=True, search=[P(1, "clip")], **S()); b.tick()
    b.found[0]["media"] = [{"type": "video", "url": "https://video.twimg.com/v.mp4", "w": 1280, "h": 720}]
    b.video_forbidden = lambda url: False
    seen, events = [], []
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/mpv" if n == "mpv" else None)
    def fake_run(url, cfg, run=None, which=None, **k):
        items = video.posts_playlist(k["posts"])
        start = video.start_index(items, k["start_n"])
        argv = video.mpv_argv(items, "sixel", "off", 120, 40, xpx=960, ypx=640, start=start,
                              scale=getattr(cfg, "video_scale", video.VIDEO_SCALE))
        seen.append(({x: v for x, v in k.items() if not callable(v)}, argv, events.count("suspend")))
        return "mpv"
    monkeypatch.setattr(video, "run_mpv", fake_run)
    app = XBotApp(bot=b, autostart=False)
    @contextlib.contextmanager
    def fake_suspend():
        events.append("suspend"); yield; events.append("resume")
    async with app.run_test(size=(120, 40)) as pilot:
        app.suspend = fake_suspend
        app.action_open_media(1)
        assert not seen  # deferred: never suspends inside the click handler
        await pilot.pause(0.3)
        app.action_show_post(1); await pilot.pause()
        await pilot.press("v"); await pilot.pause()
        assert len(seen) == 2
        (k1, a1, s1), (k2, a2, s2) = seen
        assert k1.keys() == k2.keys() and k1["start_n"] == k2["start_n"] == 1 and k1["start_sub"] == k2["start_sub"]
        assert a1 == a2 and any(x.startswith("--vf=") and "pad=" in x for x in a1) and s1 == 1 and s2 == 2
        b.stopped = True
