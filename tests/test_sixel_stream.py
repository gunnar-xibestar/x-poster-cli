"""Sixel frames reach the terminal byte-exact; controls-line updates never land inside a DCS."""
import os, time, subprocess
from xbot import video

FRAME = b"\x1b[1;1H\x1bP0;1;0q\"1;1;470;500#0;2;0;0;0" + b"?7G7GCOG7G!19A?#169??7@AAG_!5D?#7A#29!255?-" * 400 + b"\x1b\\"


def run_proxy(chunks, submits_at, pause=0.0):
    got = []
    r, w = os.pipe()
    px = video.TermProxy(r, got.append); px.thread.start()
    for i, c in enumerate(chunks):
        os.write(w, c)
        if i in submits_at:
            px.submit(f"\x1b7LINE{i}\x1b8")
        time.sleep(pause)
    time.sleep(0.15)
    os.close(w); px.thread.join(3); os.close(r)
    return b"".join(got)


def split(b, n):
    k = len(b) // n + 1
    return [b[i:i + k] for i in range(0, len(b), k)]


def outside_dcs(blob, marker):
    i = blob.index(marker)
    return blob.rfind(b"\x1bP", 0, i) < blob.rfind(b"\x1b\\", 0, i) or blob.rfind(b"\x1bP", 0, i) < 0


def test_stalled_frame_many_chunks_long_pauses():
    chunks = split(FRAME, 25)  # mpv / a slow stream stalls mid-frame, far longer than the 50 ms idle flush
    blob = run_proxy(chunks, submits_at={1, 5, 12, 20}, pause=0.12)
    lines = [b"\x1b7LINE%d\x1b8" % i for i in (20,)]  # newest wins; held until the frame's ST
    for ln in lines:
        assert ln in blob and outside_dcs(blob, ln)
    assert blob.index(b"LINE") > blob.index(b"\x1b\\")
    stripped = blob
    for i in (1, 5, 12, 20):
        stripped = stripped.replace(b"\x1b7LINE%d\x1b8" % i, b"")
    assert stripped == FRAME  # every byte passed through unchanged


def test_st_split_between_chunks():
    a, b = FRAME[:-1], FRAME[-1:]  # ESC | backslash
    blob = run_proxy([a, b], submits_at={0}, pause=0.2)
    assert blob.index(b"LINE0") > blob.index(b"\x1b\\") and blob.replace(b"\x1b7LINE0\x1b8", b"") == FRAME


def test_c1_dcs_and_st():
    c1 = b"\x90q#0;2;0;0;0" + b"~~~~-" * 2000 + b"\x9c"
    blob = run_proxy(split(c1, 10) + [b"\x1b[2;1H"], submits_at={2}, pause=0.08)
    assert blob.index(b"LINE2") > blob.index(b"\x9c") and blob.replace(b"\x1b7LINE2\x1b8", b"") == c1 + b"\x1b[2;1H"
    px = video.TermProxy(0, lambda b: None)
    px.scan(b"\x90q~~~"); assert px.in_dcs and not px.safe()
    px.scan(b"~~\x9c"); assert px.safe()


def test_dcs_safety_net_never_injects_and_logs(monkeypatch):
    logged = []
    monkeypatch.setattr(video, "log_exc", lambda e: logged.append(str(e)))
    px = video.TermProxy(0, lambda b: None)
    px.DCS_MAX_BYTES = 1000
    px.scan(b"\x1bPq" + b"~" * 2000)
    assert not px.safe() and logged and "held back" in logged[0]
    px.scan(b"~" * 5000); assert len(logged) == 1  # once


def test_write_all_handles_short_writes_and_eintr(monkeypatch):
    out = []
    calls = {"n": 0}
    real = os.write
    def fake(fd, b):
        calls["n"] += 1
        if calls["n"] == 2:
            raise InterruptedError
        if calls["n"] == 3:
            raise BlockingIOError
        b = bytes(b)[:7]  # short writes
        out.append(b); return len(b)
    monkeypatch.setattr(video.os, "write", fake)
    r, w = os.pipe()
    try:
        assert video.write_all(w, FRAME[:100])
    finally:
        monkeypatch.setattr(video.os, "write", real); os.close(r); os.close(w)
    assert b"".join(out) == FRAME[:100]


def test_mpv_stderr_never_reaches_terminal(tmp_path, monkeypatch):
    import xbot.config as C
    monkeypatch.setattr(C, "STATE_DIR", tmp_path)
    seen = {}
    def run(argv, **k):
        if argv[0] == "mpv":
            seen.update(k)
    from xbot.config import Config
    video.run_mpv("https://v/x.mp4", Config(video_vo="sixel"), run=run, which=lambda n: "/usr/bin/mpv", size=(80, 24), tty=None)
    assert seen["stderr"] not in (None,) and seen["stderr"] != subprocess.STDOUT
    assert (tmp_path / "mpv-stderr.log").exists() and "--vo-sixel-buffered=yes" in video.mpv_argv("u", "sixel")


def test_key_raw_mode_keeps_output_processing():
    import pty, termios
    m, s = pty.openpty()
    before = termios.tcgetattr(s)
    video.input_raw(s)
    a = termios.tcgetattr(s)
    assert a[1] == before[1]  # oflag (OPOST/ONLCR) untouched: output path unchanged while frames stream
    assert not a[3] & termios.ECHO and not a[3] & termios.ICANON and not a[0] & termios.IXON
    os.close(m); os.close(s)
