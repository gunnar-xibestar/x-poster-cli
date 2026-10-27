import re
from xbot.video import (mpv_argv, item_props, PostActions, StatusPainter, controls_line, parse_keys,
                        sixel_geometry, photo_boxes, area_box, pad_vf)

A = dict(cols=128, rows=36, xpx=1024, ypx=576)  # 8x16 cells
G = (128, 36, 1024, 576, None)
PHOTO = {"kind": "photo", "url": "P", "w": 160, "h": 100, "post_id": "1", "n": 1}  # small 16:10 source
TALL = {"kind": "photo", "url": "T", "w": 600, "h": 1200, "post_id": "3", "n": 3}
VID = {"kind": "video", "url": "V", "w": 1280, "h": 720, "post_id": "2", "n": 2}


def opt(a, k):
    return next(x for x in a if x.startswith(f"--{k}=")).split("=", 1)[1]


def props(cmds):
    return {c[1]: c[2] for c in cmds if c[0] == "set_property"}


def vf(cmds):
    return next(c[2] for c in cmds if c[:2] == ["vf", "set"])


def test_box_is_whole_area_from_1_1_and_constant():
    a = mpv_argv([PHOTO, VID], vo="sixel", **A)
    _, _, ac, ar, _, _ = sixel_geometry(**A)
    assert (int(opt(a, "vo-sixel-left")), int(opt(a, "vo-sixel-top"))) == (1, 1)
    assert int(opt(a, "vo-sixel-width")) == ac * 8 and int(opt(a, "vo-sixel-height")) == ar * 16
    assert "--video-unscaled=no" in a and "--{" not in a
    assert opt(a, "vf") == pad_vf(PHOTO, *G)


def test_pad_filter_centres_and_upscales():
    _, _, _, _, W, H = area_box(*G)
    f = pad_vf(PHOTO, *G)
    assert f"scale={W}:{H}:force_original_aspect_ratio=decrease" in f  # 160x100 upscaled to the box
    assert f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2" in f
    v = pad_vf(VID, *G, scale=0.6)
    bw, bh = map(int, re.search(r"scale=(\d+):(\d+)", v).groups())
    assert abs(bw - W * 0.6) <= 2 and abs(bh - H * 0.6) <= 2 and f"pad={W}:{H}" in v


def test_item_change_never_moves_left_top_and_sets_filter():
    sent = []
    p = StatusPainter([PHOTO, TALL], 128, 36, write=lambda s: None)
    p.on_move = lambda it: sent.extend(item_props(it, 128, 36, 1024, 576))
    p.st["large"] = True
    p.update("playlist-pos", 1)
    pr = props(sent)
    assert "vo-sixel-left" not in pr and "vo-sixel-top" not in pr  # mpv ignores those at runtime
    assert pr["video-zoom"] == 0 and p.st["large"] is False and vf(sent) == pad_vf(TALL, *G)


def test_large_box_uses_full_terminal_never_crops():
    n, l = photo_boxes(TALL, *G)
    assert l[3] == 35 and l[3] > n[3]
    big = area_box(*G, large=True)
    assert big[:4] == (1, 1, 128, 35)


def test_z_toggles_large_photos_only_no_video_zoom():
    sent = []
    p = StatusPainter([TALL, VID], 128, 36, write=lambda s: None)
    p.geom = G
    pa = PostActions(p, sent.append)
    assert parse_keys(b"zZ")[0] == ["z", "Z"]
    pa.key("z")
    assert p.st["large"] and "large" in p.line().split("  ·  ")
    assert props(sent)["vo-sixel-rows"] == 35 and props(sent)["video-zoom"] == 0
    assert "pad=1024:560" in vf(sent)  # padded to the large box: still centred
    sent.clear(); pa.key("z")
    assert not p.st["large"] and props(sent)["vo-sixel-rows"] < 35
    p.update("playlist-pos", 1); n = len(sent)
    assert pa.key("z") is True and len(sent) == n  # ignored on video
    assert "z large" not in controls_line("video", item=VID) and "z large" in controls_line("photo", item=TALL)


def test_z_noop_when_normal_is_max():
    p = StatusPainter([PHOTO], 1, 6, write=lambda s: None)
    p.geom = (1, 6, 8, 96, None)
    n, l = photo_boxes(PHOTO, *p.geom)
    assert n[2:4] == l[2:4]
    sent = []
    PostActions(p, sent.append).key("z")
    assert sent == [] and "max size" in p.msg and "z large" not in controls_line("photo", st=p.st, item=PHOTO)
