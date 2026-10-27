"""pause -> unpause must keep the viewer running; controls-line writes never land inside a sixel frame."""
import json, os, socket, threading, time
from xbot import video

SIXEL = b"\x1bPq#0;2;0;0;0#0~~~~-" * 50 + b"\x1b\\"


def test_pause_unpause_sequence_keeps_watcher_running():
    ours, theirs = socket.socketpair()
    out, likes = [], []
    items = video.playlist([{"type": "video", "url": "https://video.twimg.com/v.mp4"}])
    p = video.StatusPainter(items, 100, 30, write=out.append)
    t = threading.Thread(target=video.ipc_loop, args=(ours, lambda it: (likes.append(1), "liked")[1], 0),
                         kwargs={"painter": p}, daemon=True)
    t.start()
    f = theirs.makefile("rb")
    cmds = [json.loads(f.readline())["command"] for _ in video.OBSERVE]
    evs = [{"event": "property-change", "name": "time-pos", "data": 9.4},
           {"event": "property-change", "name": "pause", "data": True},
           {"event": "pause"},
           {"event": "property-change", "name": "pause", "data": False},
           {"event": "unpause"},
           {"event": "property-change", "name": "time-pos", "data": None},
           {"event": "seek"}, {"event": "playback-restart"},
           {"event": "property-change", "name": "time-pos", "data": 10.2},
           {"event": "property-change", "name": "duration", "data": "garbage"},
           {"event": "property-change", "name": "playlist-pos", "data": "x"},  # malformed: must not kill the thread
           {"event": "client-message", "args": ["xbot-like"]}]
    for ev in evs:
        theirs.sendall((json.dumps(ev) + "\n").encode())
    time.sleep(0.5)
    assert t.is_alive()  # still watching after unpause (and after a malformed event)
    assert any("PAUSED" in l for l in out) and "PAUSED" not in out[-1] and likes == [1]
    # the watcher only ever sends observe_property: nothing it does can pause, stop or quit mpv
    assert all(c[0] == "observe_property" for c in cmds)
    theirs.shutdown(socket.SHUT_RDWR); theirs.close(); t.join(2)
    assert "SPACE cycle pause" in video.INPUT_CONF.splitlines()


def test_proxy_never_writes_inside_sixel_frame():
    got = []
    r, w = os.pipe()
    px = video.TermProxy(r, got.append)
    px.thread.start()
    half = len(SIXEL) // 2
    os.write(w, SIXEL[:half]); time.sleep(0.15)
    px.submit("\x1b7STATUS\x1b8")  # arrives mid-frame
    time.sleep(0.15)
    assert b"STATUS" not in b"".join(got)  # held back while the DCS is open
    os.write(w, SIXEL[half:] + b"\x1b[5;"); time.sleep(0.15)
    assert b"STATUS" not in b"".join(got)  # half-written CSI: still not safe
    os.write(w, b"1H"); time.sleep(0.15)
    os.close(w); px.thread.join(2); os.close(r)
    blob = b"".join(got)
    assert blob.index(b"STATUS") > blob.index(b"\x1b[5;1H") > blob.index(SIXEL[-2:])
    assert blob.replace(b"\x1b7STATUS\x1b8", b"") == SIXEL + b"\x1b[5;1H"  # mpv's bytes pass through unchanged


def test_proxy_flushes_when_idle_photo():
    got = []
    r, w = os.pipe()
    px = video.TermProxy(r, got.append); px.thread.start()
    os.write(w, SIXEL); time.sleep(0.1)
    px.submit("LINE"); time.sleep(0.2)  # no more output from mpv (still photo): line still goes out
    assert got[-1] == b"LINE"
    os.close(w); px.thread.join(2); os.close(r)


def test_run_mpv_routes_stdout_through_proxy_and_records_rc():
    calls, st = [], {}
    class R:
        returncode = 2
    def run(argv, **k):
        calls.append(k)
        if argv[0] == "mpv":
            os.write(k["stdout"], SIXEL)
            return R()
    from xbot.config import Config
    assert video.run_mpv("https://v/x.mp4", Config(video_vo="sixel"), run=run, which=lambda n: "/usr/bin/mpv",
                         size=(80, 24), tty=None, state=st) == "mpv"
    assert isinstance(calls[0]["stdout"], int) and st["rc"] == 2
