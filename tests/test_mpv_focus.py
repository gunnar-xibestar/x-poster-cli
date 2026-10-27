"""mpv must never open a GUI window (WSLg focus steal) and A/D is always on the controls line."""
import json, socket, threading, time
from xbot import video
from xbot.config import Config

GUI = {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0", "WAYLAND_SOCKET": "5", "XDG_SESSION_TYPE": "wayland",
       "XAUTHORITY": "/x", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/b", "PATH": "/usr/bin", "TERM": "xterm-256color",
       "WT_SESSION": "1", "XDG_RUNTIME_DIR": "/run/user/1000", "XAI_API_KEY": "sk-secret"}


def test_mpv_env_has_no_display_vars_or_secrets():
    env = video.mpv_env(GUI)
    for k in ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "XDG_SESSION_TYPE", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS", "XAI_API_KEY"):
        assert k not in env, k
    assert env["PATH"] == "/usr/bin" and env["TERM"] == "xterm-256color" and env["WT_SESSION"] == "1"
    assert env["XDG_RUNTIME_DIR"] == "/run/user/1000"  # native Linux: audio still needs it
    wsl = video.mpv_env(dict(GUI, WSL_DISTRO_NAME="Ubuntu", PULSE_SERVER="unix:/mnt/wslg/PulseServer"))
    assert "XDG_RUNTIME_DIR" not in wsl and wsl["PULSE_SERVER"].startswith("unix:/mnt/wslg")  # no wayland-0 fallback


def test_run_mpv_passes_gui_free_env(monkeypatch):
    for k, v in GUI.items():
        monkeypatch.setenv(k, v)
    calls = []
    video.run_mpv("https://v/x.mp4", Config(video_vo="sixel"), run=lambda a, **k: calls.append((a, k)),
                  which=lambda n: "/usr/bin/mpv", size=(80, 24), tty=None)
    argv, k = calls[0]
    assert argv[0] == "mpv" and not {"DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "XDG_SESSION_TYPE"} & set(k["env"])


def test_mpv_flags_no_window_explicit_vo():
    for vo in ("sixel", "tct"):
        a = video.mpv_argv(["u1", "u2"], vo)
        for f in ("--force-window=no", "--input-terminal=no", "--terminal=yes", "--idle=no", "--hwdec=no",
                  "--audio-display=no", "--stop-screensaver=no"):
            assert f in a, f
        assert "--no-terminal" not in a and "--terminal=no" not in a
        vos = [x for x in a if x.startswith("--vo=")]
        assert vos == [f"--vo={vo}"] and "," not in vos[0]  # one explicit vo, no fallback list
    assert video.resolve_vo("auto", {"TERM": "xterm"}) in ("sixel", "tct")


def _drive(items, start, events):
    ours, theirs = socket.socketpair()
    out = []
    p = video.StatusPainter(items, 100, 30, write=out.append, start=start)
    t = threading.Thread(target=video.ipc_loop, args=(ours, None, 0), kwargs={"painter": p}, daemon=True); t.start()
    f = theirs.makefile("rb")
    for _ in video.OBSERVE:
        f.readline()
    for ev in events:
        theirs.sendall((json.dumps(ev) + "\n").encode()); time.sleep(0.05)
    theirs.shutdown(socket.SHUT_RDWR); theirs.close(); t.join(2)
    return out


def test_ad_always_shown_and_end_note():
    one = video.playlist([{"type": "photo", "url": "https://pbs.twimg.com/a.jpg"}])
    assert all("←/→ prev/next" in l for l in [video.controls_line("photo", 0, 1), video.controls_line("video", 0, 1)])
    nxt = {"event": "client-message", "args": ["xbot-next"]}
    prv = {"event": "client-message", "args": ["xbot-prev"]}
    out = _drive(one, 0, [nxt])
    assert "no more media" in out[-1] and "←/→ prev/next" in out[-1]
    out = _drive(one, 0, [prv])
    assert "first item" in out[-1]
    two = video.playlist([{"type": "photo", "url": "https://pbs.twimg.com/a.jpg"}, {"type": "photo", "url": "https://pbs.twimg.com/b.jpg"}])
    out = _drive(two, 0, [nxt])
    assert not any("no more media" in l for l in out)  # not at the end: plain move
    pos1 = {"event": "property-change", "name": "playlist-pos", "data": 1}
    out = _drive(two, 0, [pos1, nxt])  # move landed before the key's message: no false end note
    assert "2/2" in out[-1] and not any("no more media" in l for l in out)
