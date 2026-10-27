"""xbot reads the tty itself and forwards keys to mpv over IPC; mouse/focus/paste reports are dropped."""
import json, os, socket, threading, time
from xbot import video


def test_parse_keys_maps_viewer_keys():
    keys, rest = video.parse_keys(b"aAdD lLmqQ\x1b[A\x1b[B\x1b[C\x1b[D\x1bOC\x03")
    assert keys == ["a", "A", "d", "D", "SPACE", "l", "L", "m", "q", "Q", "UP", "DOWN", "RIGHT", "LEFT", "RIGHT", "q"]
    assert rest == b""
    assert video.parse_keys(b"\x1b") == ([], b"\x1b")  # lone ESC: decided after a timeout
    assert video.parse_keys(b"\x1b\x1b[C") == (["ESC", "RIGHT"], b"")


def test_parse_keys_drops_mouse_focus_paste_and_unknown():
    junk = (b"\x1b[MCk?\x1b[MCl?\x1b[M@~@"      # X10 / normal mouse reports (from the screenshot)
            b"\x1b[<35;12;40M\x1b[<0;1;1m"       # SGR mouse
            b"\x1b[I\x1b[O"                      # focus in/out
            b"\x1b[200~pasted aaa ddd\x1b[201~"  # bracketed paste
            b"\x1b[1;5C\x1b[15~xyw")             # modified arrow, F5, unmapped letters (z is zoom)
    keys, rest = video.parse_keys(junk + b"d")
    assert keys == ["d"] and rest == b""
    k, r = video.parse_keys(b"\x1b[MC")  # mouse report split across reads: held, not echoed
    assert k == [] and r == b"\x1b[MC"
    assert video.parse_keys(r + b"k?a") == (["a"], b"")


def test_key_reader_forwards_keypresses_and_esc_timeout():
    r, w = os.pipe()
    sent = []
    kr = video.KeyReader(r, sent.append); kr.thread.start()
    os.write(w, b"D"); time.sleep(0.05)
    os.write(w, b"\x1b[MCk?A \x1b[C"); time.sleep(0.05)
    os.write(w, b"l"); time.sleep(0.05)
    os.write(w, b"\x1b"); time.sleep(0.2)  # lone ESC -> Esc after the wait
    os.write(w, b"q"); time.sleep(0.05)
    kr.stop(); os.close(r); os.close(w)
    assert sent == [["keypress", k] for k in ("D", "A", "SPACE", "RIGHT", "l", "ESC", "q")]


def test_input_conf_has_bindings_for_forwarded_keys():
    conf = dict(l.split(" ", 1) for l in video.INPUT_CONF.strip().splitlines())
    for k in ("a", "A", "d", "D", "SPACE", "LEFT", "RIGHT", "UP", "DOWN", "m", "q", "ESC"):
        assert k in conf, k
    assert conf["SPACE"] == "cycle pause" and conf["ESC"] == "quit"
    a = video.mpv_argv("u", "sixel")
    assert "--input-terminal=no" in a and "--input-terminal=yes" not in a and "--force-window=no" in a


def test_run_mpv_modes_off_before_launch_and_keys_via_ipc(tmp_path, monkeypatch):
    import pty, termios
    master, slave = pty.openpty()
    name = os.ttyname(slave)
    before = termios.tcgetattr(slave)
    order, seen = [], []
    real_write = os.write
    def run(argv, **k):
        if argv[0] != "mpv":
            return None
        order.append("mpv")
        assert k["stdin"] is not None and k["stdin"] != slave  # mpv doesn't read the terminal
        attrs = termios.tcgetattr(slave)
        assert not attrs[3] & termios.ECHO and not attrs[3] & termios.ICANON  # raw while mpv runs
        fd = int([x for x in argv if x.startswith("--input-ipc-client=fd://")][0].split("//")[1])
        mpv_sock = socket.socket(fileno=os.dup(fd))
        real_write(master, b"\x1b[MCk?D \x1b[D"); time.sleep(0.3)
        mpv_sock.settimeout(1)
        buf = b""
        while buf.count(b"keypress") < 3:
            buf += mpv_sock.recv(65536)
        seen.extend(json.loads(l)["command"] for l in buf.splitlines() if b"keypress" in l)
        mpv_sock.close()
        return None
    from xbot.config import Config
    video.run_mpv("https://v/x.mp4", Config(video_vo="tct"), run=run, which=lambda n: "/usr/bin/mpv",
                  size=(80, 24), tty=name)
    termout = b""
    os.set_blocking(master, False)
    try:
        while True:
            termout += os.read(master, 65536)
    except (BlockingIOError, OSError):
        pass
    assert seen == [["keypress", "D"], ["keypress", "SPACE"], ["keypress", "LEFT"]]  # mouse report dropped
    assert video.MOUSE_OFF.encode() in termout and termout.index(video.MOUSE_OFF.encode()) == 0  # first thing written
    for m in ("1000", "1002", "1003", "1005", "1006", "1015", "1004", "2004"):
        assert f"\x1b[?{m}l" in video.MOUSE_OFF
    after = termios.tcgetattr(slave)
    assert after[3] & termios.ECHO and after[3] & termios.ICANON  # restored (echo + canonical back)
    assert b"Ck?" not in termout  # nothing echoed
    os.close(master); os.close(slave)
