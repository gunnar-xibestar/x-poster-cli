from xbot import video
from xbot.config import Config
from tests.test_search import S

MP4 = "video/mp4"


def test_pick_variant_closest_to_832k():
    vs = [{"content_type": "application/x-mpegURL", "url": "m3u8"},
          {"content_type": MP4, "bit_rate": 256000, "url": "low"},
          {"content_type": MP4, "bit_rate": 832000, "url": "mid"},
          {"content_type": MP4, "bit_rate": 2176000, "url": "high"}]
    assert video.pick_variant(vs) == "mid"
    assert video.pick_variant(vs[:2] + vs[3:]) == "low"  # 256k is closer to 832k than 2176k
    assert video.pick_variant([{"content_type": MP4, "bit_rate": 0, "url": "gif.mp4"}]) == "gif.mp4"  # GIF: single mp4
    assert video.pick_variant([]) is None and video.pick_variant(None) is None and video.pick_variant(vs[:1]) is None


def test_media_item_uses_picker():
    from xbot.xapi import _media_item, MEDIA_PARAMS
    m = _media_item({"type": "video", "preview_image_url": "p", "duration_ms": 5000, "variants": [
        {"content_type": MP4, "bit_rate": 832000, "url": "mid"}, {"content_type": MP4, "bit_rate": 2176000, "url": "high"}]})
    assert m["url"] == "mid" and m["duration_ms"] == 5000
    for f in ("variants", "preview_image_url", "duration_ms", "type"):
        assert f in MEDIA_PARAMS["media.fields"]


def test_run_mpv_mocked_and_missing():
    calls = []
    cfg = Config(video_vo="tct", video_audio="off")
    assert video.run_mpv("https://v/x.mp4", cfg, run=lambda argv, **k: calls.append((argv, k)), which=lambda n: "/usr/bin/mpv", size=(90, 25)) == "mpv"
    argv, kw = calls[0]
    assert "--vo=tct" in argv and "--mute=yes" in argv and "--vo-tct-width=90" in argv and kw["pass_fds"]
    assert video.run_mpv("u", cfg, run=lambda *a, **k: 1 / 0, which=lambda n: None) == "missing"


def vpost():
    return {"id": "1", "text": "clip", "author_id": "a", "username": "a", "conversation_id": "1",
            "media": [{"type": "video", "url": "https://video.twimg.com/old.mp4", "preview_image_url": "https://pbs.twimg.com/p.jpg"}]}


def test_403_refetches_once(mk):
    b = mk(xonly=True, search=[vpost()], **S()); b.tick()
    got = []
    class RX:
        def get_post(self, pid):
            got.append(pid); return {"id": pid, "media": [{"type": "video", "url": "https://video.twimg.com/new.mp4"}]}
    b.dry_x.get_post = RX().get_post
    checks = []
    def forbidden(u):
        checks.append(u); return True
    assert b.video_url(1, forbidden=forbidden).endswith("new.mp4") and len(checks) == 1 and got == ["1"]
    assert b.found_post(1)["media"][0]["url"].endswith("new.mp4")


def test_auto_vo_falls_back_to_tct_without_pixel_size():
    env = {"WEZTERM_PANE": "1", "TERM": "xterm-256color"}
    assert video.resolve_vo("auto", env, pixels_known=False) == "tct"
    assert video.resolve_vo("auto", {"WT_SESSION": "1", "TERM": "xterm"}, pixels_known=False) == "sixel"  # WT: estimate
    assert video.resolve_vo("auto", env, pixels_known=True) == "sixel"
    assert video.resolve_vo("sixel", env, pixels_known=False) == "sixel"


def test_input_path_tty_stdin_and_terminal_restored(tmp_path):
    tty = tmp_path / "tty"; tty.write_text("")
    calls = []
    def run(argv, **k):
        calls.append((argv, k))
        if argv[0] == "mpv":
            fd = k["pass_fds"][0]
            assert os.read(fd, 4096).decode() == video.INPUT_CONF  # bindings come from the pipe
    import os
    cfg = Config(video_vo="auto")
    assert video.run_mpv("https://v/x.mp4", cfg, run=run, which=lambda n: "/usr/bin/mpv", size=(80, 24, 0, 0),
                         env={"WEZTERM_PANE": "1"}, tty=str(tty)) == "mpv"
    argv, k = calls[0]
    assert argv[0] == "mpv" and "--vo=tct" in argv  # no pixel size: tct
    import subprocess
    assert k["stdin"] == subprocess.DEVNULL  # mpv never reads the tty; xbot forwards keys over IPC
    assert any(c[0][:2] == ["stty", "sane"] for c in calls[1:])  # terminal restored after mpv


def test_best_variant_fits_terminal():
    vs = [{"content_type": MP4, "bit_rate": 256000, "url": "https://v/vid/480x270/a.mp4"},
          {"content_type": MP4, "bit_rate": 832000, "url": "https://v/vid/640x360/b.mp4"},
          {"content_type": MP4, "bit_rate": 2176000, "url": "https://v/vid/1280x720/c.mp4"}]
    assert video.best_variant(vs, max_h=800).endswith("c.mp4")
    assert video.best_variant(vs, max_h=400).endswith("b.mp4")
    assert video.best_variant(vs, max_h=100).endswith("c.mp4")  # nothing fits: sharpest
    assert video.best_variant([{"content_type": MP4, "url": "g.mp4"}]) == "g.mp4" and video.best_variant([]) is None


def test_run_mpv_uses_best_variant():
    calls = []
    vs = [{"content_type": MP4, "bit_rate": 832000, "url": "https://v/vid/640x360/b.mp4"},
          {"content_type": MP4, "bit_rate": 2176000, "url": "https://v/vid/1280x720/c.mp4"}]
    video.run_mpv("https://v/vid/640x360/b.mp4", Config(video_vo="sixel"), run=lambda a, **k: calls.append(a),
                  which=lambda n: "/usr/bin/mpv", size=(120, 40, 0, 0), tty=None, variants=vs)
    assert [x for x in calls[0] if x != "--}"][-1].endswith("c.mp4")  # 39 rows x 20 px = 780 px >= 720
