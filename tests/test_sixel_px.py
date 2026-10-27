import os, pty
from xbot import video
from xbot.config import Config
from xbot.configcli import validate
import pytest


@pytest.fixture(autouse=True)
def _no_probe(monkeypatch):
    monkeypatch.setattr(video, "probed_cell", lambda: None)


def test_parse_px_reports():
    assert video.parse_px_reports(b"\x1b[4;600;1000t\x1b[6;20;10t") == (1000, 600, 10, 20)
    assert video.parse_px_reports(b"junk") == (0, 0, 0, 0)


def test_fallback_cell_is_replaced_by_real_text_area():
    # WSL: TIOCGWINSZ pixels 0, no probe -> old code used CELL_PX 8x16 (box ~78% of the screen)
    assert video.resolve_px(100, 30, 0, 0, (1000, 600, 0, 0), probed=(0, 0) or None) == (1000, 600)
    assert video.resolve_px(100, 30, 0, 0, (0, 0, 10, 20), probed=None) == (1000, 600)


def test_largest_consistent_wins_and_photo_video_share_box():
    xp, yp = video.resolve_px(100, 30, 800, 480, (1000, 600, 10, 20), probed=(8, 16))
    assert (xp, yp) == (1000, 600)
    photo = video.area_box(100, 30, xp, yp)
    vid = video.area_box(100, 30, xp, yp)
    assert photo == vid and photo[4] == 99 * 10  # all but one column, real 10 px cells
    vf = video.pad_vf({"kind": "video"}, 100, 30, xp, yp, scale=0.6)
    assert f"pad={photo[4]}:{photo[5]}" in vf


def test_inconsistent_report_ignored():
    # a bogus 14t (absurd aspect) must not win over a sane one
    assert video.resolve_px(100, 30, 1000, 600, (5000, 100, 0, 0), probed=None) == (1000, 600)


def test_sixel_scale_override():
    assert video.resolve_px(100, 30, 800, 480, (0, 0, 0, 0), probed=None, sixel_scale="1.25") == (1000, 600)
    assert video.resolve_px(100, 30, 0, 0, (0, 0, 0, 0), probed=None, sixel_scale="1.25") == (1000, 600)
    assert video.resolve_px(100, 30, 800, 480, (0, 0, 0, 0), probed=None, sixel_scale="auto") == (800, 480)


def test_sixel_scale_config_validation():
    c = Config(); assert c.sixel_scale == "auto"; validate(c); assert c.sixel_scale == "auto"
    c.sixel_scale = "1.25"; validate(c); assert c.sixel_scale == "1.25"
    for bad in ("big", "9"):
        c.sixel_scale = bad
        with pytest.raises(ValueError):
            validate(c)


def test_query_term_px_reads_answers_from_tty():
    master, slave = pty.openpty()
    name = os.ttyname(slave)
    os.write(master, b"\x1b[4;600;1000t\x1b[6;20;10t")  # terminal's answers already waiting
    try:
        assert video.query_term_px(name, timeout=0.5) == (1000, 600, 10, 20)
        assert os.read(master, 256).endswith(b"\x1b[14t\x1b[16t")  # the queries went to the terminal
    finally:
        os.close(master); os.close(slave)
    assert video.query_term_px("/nonexistent/tty") == (0, 0, 0, 0)
