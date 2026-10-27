"""No media-viewer picture or controls line is left in the terminal after the viewer or xbot exits."""
import io, os, time
from xbot import video


def test_enter_and_leave_sequences():
    assert video.ENTER_VIEWER.startswith("\x1b[?1049h") and video.CLEAR in video.ENTER_VIEWER
    lv = video.LEAVE_VIEWER
    assert lv.startswith("\x1b\\")  # close any open sixel DCS first
    # wipe the viewer screen, leave it, wipe the normal screen: 2J + 3J (scrollback, sixel) + home, twice
    assert lv.index(video.CLEAR) < lv.index("\x1b[?1049l") < lv.rindex(video.CLEAR)
    assert video.CLEAR == "\x1b[2J\x1b[3J\x1b[H"
    assert "--vo-sixel-alt-screen=no" in video.mpv_argv("u", "sixel")  # mpv can't leave our alt screen early


def test_restore_terminal_writes_leave_sequence():
    buf = io.StringIO()
    video.restore_terminal(run=lambda *a, **k: None, out=buf)
    assert buf.getvalue() == video.LEAVE_VIEWER


def test_run_mpv_order_alt_screen_frames_then_cleanup(monkeypatch):
    import pty
    master, slave = pty.openpty()
    name = os.ttyname(slave)
    left = []
    monkeypatch.setattr(video, "restore_terminal", lambda run=None, out=None: left.append("restore"))
    def run(argv, **k):
        if argv[0] == "mpv":
            os.write(k["stdout"], b"\x1bPq~~~~\x1b\\")
    from xbot.config import Config
    video.run_mpv("https://v/x.mp4", Config(video_vo="sixel"), run=run, which=lambda n: "/usr/bin/mpv",
                  size=(80, 24), tty=name)
    time.sleep(0.1)
    os.set_blocking(master, False)
    out = b""
    try:
        while True:
            out += os.read(master, 65536)
    except (BlockingIOError, OSError):
        pass
    assert out.index(video.ENTER_VIEWER.encode()) < out.index(b"\x1bPq~~~~\x1b\\")  # frames inside the alt screen
    assert left == ["restore"]
    os.close(master); os.close(slave)


def test_late_controls_line_dropped_after_mpv_exit():
    got = []
    r, w = os.pipe()
    px = video.TermProxy(r, got.append); px.thread.start()
    os.write(w, b"\x1bPq~~"); time.sleep(0.1)
    px.submit("LATE")  # still inside a frame when mpv exits
    os.close(w)  # mpv gone mid-frame: the held line is discarded, never painted after the viewer
    px.thread.join(2); os.close(r)
    assert b"LATE" not in b"".join(got)


def test_exit_summary_printed_on_clean_screen():
    from xbot.app import clear_leftovers
    buf = io.StringIO()
    clear_leftovers(buf)
    assert buf.getvalue().endswith(video.CLEAR) and buf.getvalue().startswith("\x1b\\")
    class NotTTY(io.StringIO):
        def isatty(self): return False
    import sys
    old = sys.stderr; sys.stderr = NotTTY()
    try:
        clear_leftovers(); assert sys.stderr.getvalue() == ""  # piped stderr: no escape codes
    finally:
        sys.stderr = old


import pytest


@pytest.mark.parametrize("how", ["quit", "ctrl_c", "limit"])
def test_every_exit_path_clears_then_prints_only_summary(monkeypatch, how):
    import io, sys
    from xbot import app as appmod
    from xbot.video import CLEAR
    buf = io.StringIO()
    buf.isatty = lambda: True

    class Fake:
        bot = None
        _cli_mode = False
        _session_line = "xbot: session 1m · API $0.10 · last 5 days $1.00"
        def run(self):
            print("\x1bPq#0~~\x1b\\ controls", file=sys.stderr)  # viewer leftovers
            if how == "ctrl_c":
                raise KeyboardInterrupt
            if how == "limit":
                self._session_line = "xbot: spend limit reached · last 5 days $5.00"
        def shutdown(self):
            pass
    monkeypatch.setattr(appmod, "XBotApp", Fake)
    monkeypatch.setattr(appmod, "probe_graphics", lambda: None)
    monkeypatch.setattr(sys, "stderr", buf)
    monkeypatch.setenv("XBOT_INSECURE_ENV", "1")
    try:
        appmod.main([])
    except SystemExit:
        pass
    out = buf.getvalue()
    tail = out[out.rindex(CLEAR) + len(CLEAR):]
    assert tail.strip().startswith("xbot:") and "controls" not in tail and "\x1bP" not in tail
