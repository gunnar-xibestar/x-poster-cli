import json, socket, threading
from PIL import Image as PILImage
from xbot import video
from xbot.app import XBotApp, PostCard
from xbot.config import Config
from tests.test_search import S
from tests.test_media_layout import P


def test_run_mpv_wires_ipc_when_like_given():
    calls = []
    def run(argv, **k):
        calls.append((argv, k))
    video.run_mpv("https://v/x.mp4", Config(), run=run, which=lambda n: "/usr/bin/mpv", size=(80, 24), tty=None,
                  on_like=lambda: "ok")
    argv, k = calls[0]
    ipc = [x for x in argv if x.startswith("--input-ipc-client=fd://")]
    assert ipc and int(ipc[0].split("//")[1]) in k["pass_fds"] and len(k["pass_fds"]) == 2


async def test_like_once_from_player_marks_once_and_rolls_back(mk):
    b = mk(xonly=True, search=[P(1, "clip")], **S()); b.tick()
    res = [(False, "like not sent: X rate limit (429)"), (True, "liked #1")]
    b.like_post = lambda n: res.pop(0)
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(120, 40)):
        assert app.like_once(1) == (False, "like not sent: X rate limit (429)") and b.state.liked == []
        assert app.like_once(1) == (True, "liked #1") and b.state.liked == ["1"]
        assert app.like_once(1) == (True, "already liked") and not res
        b.stopped = True
