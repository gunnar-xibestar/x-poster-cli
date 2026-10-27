from xbot.video import fit_box, mpv_argv, clamp_scale, sixel_geometry
from xbot.config import Config
from xbot.configcli import validate
import pytest

# 128x40 cells of 8x16 px  -> picture area 127 x 36 cells
A = dict(cols=128, rows=40, xpx=1024, ypx=640)


def test_photo_full_area_centred():
    _, _, ac, ar, _, _ = sixel_geometry(**A)
    l, t, c, r, w, h = fit_box(**A, kind="photo", w=1000, h=1000)
    assert r == ar and c < ac and l == 1 + (ac - c) // 2 and t == 1


def test_video_60pct_aspect_fit_and_centred():
    _, _, ac, ar, _, _ = sixel_geometry(**A)
    l, t, c, r, w, h = fit_box(**A, kind="video", w=1920, h=1080, scale=0.6)
    assert c <= int(ac * 0.6) + 1 and r <= int(ar * 0.6) + 1
    assert abs((c * 8) / (r * 16) - 16 / 9) < 0.2
    assert l == 1 + (ac - c) // 2 and t == 1 + (ar - r) // 2 and l > 1 and t > 1
    assert (w, h) == (c * 8, r * 16)


def test_unknown_size_box_is_scaled_area():
    _, _, ac, ar, _, _ = sixel_geometry(**A)
    l, t, c, r, *_ = fit_box(**A, kind="video", scale=0.5)
    assert c == int(ac * 0.5) and r == int(ar * 0.5)


def test_scale_bounds():
    assert clamp_scale(5) == 1.0 and clamp_scale(0.01) == 0.2 and clamp_scale("x") == 0.6
    c = Config(); c.video_scale = 1.5
    with pytest.raises(ValueError):
        validate(c)
    c.video_scale = 0.6; validate(c)


def test_argv_has_no_per_file_groups_video_scale_in_filter():
    items = [{"kind": "video", "url": "V", "w": 1280, "h": 720}]
    a = mpv_argv(items, vo="sixel", **A, scale=0.6)
    assert "--{" not in a and a[-2:] == ["--", "V"]
    assert any(x.startswith("--vf=lavfi=[") and "fast_bilinear" in x for x in a) and "--framedrop=vo" in a
