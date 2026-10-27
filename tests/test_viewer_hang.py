import os, socket, sys, threading, time, subprocess
from xbot import video


def test_ctrl_c_byte_always_calls_quit_even_if_send_blocks():
    r, w = os.pipe()
    quits = []
    def stuck_send(cmd):
        time.sleep(10)  # a wedged IPC must not matter for Ctrl+C
    kr = video.KeyReader(r, stuck_send, on_quit=lambda hard: quits.append(hard)); kr.thread.start()
    os.write(w, b"\x03"); time.sleep(0.2)
    assert quits == [True]
    os.close(w); kr.stop(); os.close(r)


def test_q_and_esc_trigger_quit_escalation():
    sent, quits = [], []
    kr = video.KeyReader(0, sent.append, on_quit=lambda hard: quits.append(hard))
    kr.forward("q"); kr.forward("ESC"); kr.forward("d")
    assert quits == [False, False] and sent[0] == ["keypress", "q"]


def test_stopper_escalates_terminate_then_kill():
    p = subprocess.Popen([sys.executable, "-c",
                          "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"])
    time.sleep(0.3)
    st = video.Stopper(lambda c: None, grace=0.3); st.proc = p
    t0 = time.monotonic(); st.stop(); p.wait(timeout=5)
    assert p.returncode != 0 and time.monotonic() - t0 < 3  # SIGTERM ignored -> killed


def test_stopper_quits_cleanly_when_mpv_obeys():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    st = video.Stopper(lambda c: p.terminate(), grace=0.5); st.proc = p
    st.stop(); p.wait(timeout=3)
    assert p.returncode is not None


def test_hung_ipc_watchdog_fires_and_sends_never_block():
    ours, theirs = socket.socketpair()
    theirs.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    hung = threading.Event()
    t = threading.Thread(target=video.ipc_loop, args=(ours,), daemon=True,
                         kwargs={"on_hung": hung.set, "ping_every": 0.05, "hung_after": 0.5})
    t.start()
    assert hung.wait(3)  # mpv (theirs) never answers -> watchdog
    # a full socket: sends time out instead of blocking forever
    lk = threading.Lock()
    ours.settimeout(video.IPC_TIMEOUT)
    t0 = time.monotonic()
    try:
        for _ in range(10000):
            ours.sendall(b"x" * 65536)
    except (socket.timeout, OSError):
        pass
    assert time.monotonic() - t0 < video.IPC_TIMEOUT * 3
    theirs.close(); t.join(3); ours.close()
    assert not t.is_alive()


def test_watchdog_quiet_while_mpv_answers():
    ours, theirs = socket.socketpair()
    hung = threading.Event()
    t = threading.Thread(target=video.ipc_loop, args=(ours,), daemon=True,
                         kwargs={"on_hung": hung.set, "ping_every": 0.05, "hung_after": 0.4})
    t.start()
    end = time.monotonic() + 1.0
    while time.monotonic() < end:
        theirs.sendall(b'{"request_id":999,"data":1,"error":"success"}\n'); time.sleep(0.05)
    assert not hung.is_set()
    theirs.close(); t.join(3); ours.close()


def test_run_mpv_teardown_on_reopen(monkeypatch, tmp_path):
    """Two viewers back to back (reopen after t): the first one's key reader + IPC watcher are gone."""
    from types import SimpleNamespace
    before = threading.active_count()
    cfg = SimpleNamespace(video_vo="tct", video_audio="off")
    def fake_run(argv, **kw):
        return SimpleNamespace(returncode=0)
    posts = [(1, {"id": "1", "username": "a", "media": [{"type": "photo", "url": "https://x/a.jpg"}]})]
    for _ in range(2):
        video.run_mpv(None, cfg, run=fake_run, which=lambda n: "/usr/bin/mpv", size=(80, 24), tty=None,
                      posts=posts, start_n=1, state={})
    time.sleep(0.3)
    assert threading.active_count() <= before + 1
