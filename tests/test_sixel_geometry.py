"""Sixel picture box never reaches the reserved controls rows, even for tall photos / unknown cell size."""
import json, socket, threading, time
from xbot import video


def test_geometry_from_pty_pixels():
    left, top, c, r, w, h = video.sixel_geometry(100, 50, xpx=900, ypx=1000)  # 9x20 cells
    assert (left, top, c, r) == (1, 1, 99, 46) and (w, h) == (891, 920)
    assert top + r <= 50 - video.STATUS_ROWS - 1  # last picture row + spare row stay above the controls rows


def test_geometry_uses_probe_then_safe_default(monkeypatch):
    monkeypatch.setattr(video, "probed_cell", lambda: (9, 19))
    assert video.sixel_geometry(120, 40)[4:] == (119 * 9, 36 * 19)  # WSL: 0 pixels -> startup probe
    monkeypatch.setattr(video, "probed_cell", lambda: None)
    assert video.sixel_geometry(120, 40)[4:] == (119 * video.CELL_PX[0], 36 * video.CELL_PX[1])
    assert video.CELL_PX[1] <= 16  # default errs small: a too-small guess shrinks the picture, never overlaps


def test_tall_photo_fits_inside_box_above_controls(monkeypatch):
    monkeypatch.setattr(video, "probed_cell", lambda: None)
    for cols, rows, xp, yp in [(120, 40, 0, 0), (200, 55, 2000, 1155), (80, 24, 0, 0), (60, 10, 0, 0)]:
        a = video.mpv_argv([{"kind": "photo", "url": "https://pbs.twimg.com/media/tall.jpg"}], "sixel", "off", cols, rows,
                           xpx=xp, ypx=yp)
        g = {k: int(v) for k, v in (x[2:].split("=") for x in a if x.startswith("--vo-sixel-") and x.split("=")[1].isdigit())}
        cw, ch = (xp // cols, yp // rows) if xp else video.CELL_PX
        assert g["vo-sixel-height"] == g["vo-sixel-rows"] * ch and g["vo-sixel-width"] == g["vo-sixel-cols"] * cw
        assert g["vo-sixel-top"] + g["vo-sixel-rows"] <= rows - video.STATUS_ROWS - 1, (cols, rows)
        # a 1:3 portrait photo scaled to fit (keepaspect) is limited by the box height, not the window
        img_h = min(g["vo-sixel-height"], g["vo-sixel-width"] * 3)
        assert img_h <= (rows - video.STATUS_ROWS - 1) * ch
        assert "--keepaspect=yes" in a and not any("exit-clear" in x for x in a) and "--vo-sixel-alt-screen=no" in a


def test_controls_line_repainted_after_load_and_again_later(monkeypatch):
    monkeypatch.setattr(video, "REPAINT_DELAY", 0.05)
    ours, theirs = socket.socketpair()
    out = []
    p = video.StatusPainter(video.playlist([{"type": "photo", "url": "https://pbs.twimg.com/a.jpg"}]), 100, 30, write=out.append)
    t = threading.Thread(target=video.ipc_loop, args=(ours, None, 0), kwargs={"painter": p}, daemon=True); t.start()
    f = theirs.makefile("rb")
    for _ in video.OBSERVE:
        f.readline()
    n0 = len(out)
    theirs.sendall(b'{"event":"file-loaded"}\n'); time.sleep(0.2)
    assert len(out) >= n0 + 2  # immediately and after the delay, even though the text didn't change
    n1 = len(out)
    theirs.sendall(b'{"event":"playback-restart"}\n'); time.sleep(0.2)
    theirs.shutdown(socket.SHUT_RDWR); theirs.close(); t.join(2)
    assert len(out) >= n1 + 2 and all("\x1b[30;1H" in l for l in out)
