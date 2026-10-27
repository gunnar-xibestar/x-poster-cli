"""A/D in the mpv viewer cross into the next/previous post with media; l likes the post on screen."""
import contextlib, json, socket, threading, time
from xbot import video
from xbot.app import XBotApp, PostCard, search_cli
from xbot.config import Config
from tests.test_search import S
from tests.test_media_layout import P

PH = lambda u: {"type": "photo", "url": f"https://pbs.twimg.com/media/{u}.jpg"}
VD = lambda u: {"type": "video", "url": f"https://video.twimg.com/{u}.mp4"}


def posts():
    a = dict(P(1, "two pics"), media=[PH("a1"), PH("a2")])
    b = P(2, "no media")
    c = dict(P(3, "vid"), media=[VD("c1")])
    d = dict(P(4, "dead link"), media=[{"type": "photo", "url": None}])
    e = dict(P(5, "mixed"), media=[VD("e1"), PH("e2")])
    return [(1, a), (2, b), (3, c), (4, d), (5, e)]


def test_posts_playlist_skips_posts_without_media_and_labels():
    items = video.posts_playlist(posts())
    assert [(i["n"], i["sub"], i["sub_count"], i["post_idx"]) for i in items] == [
        (1, 1, 2, 1), (1, 2, 2, 1), (3, 1, 1, 2), (5, 1, 2, 3), (5, 2, 2, 3)]
    assert all(i["post_count"] == 3 for i in items)
    assert video.start_index(items, 3) == 2 and video.start_index(items, 5) == 3 and video.start_index(items, 2) == 0
    ln = video.controls_line(items[4]["kind"], 4, len(items), item=items[4])
    assert ln.startswith("post 3/3  ·  @s5  ·  2/2  ·  photo") and "←/→ prev/next" in ln and "seek" not in ln
    v = video.controls_line(items[2]["kind"], 2, len(items), item=items[2])
    assert v.startswith("post 2/3  ·  @s3  ·  1/1  ·  video") and "←/→ prev/next" in v and "space pause" in v  # A/D: other posts
    one = video.posts_playlist([(1, dict(P(1, "x"), media=[PH("z")]))])
    assert "←/→ prev/next" in video.controls_line("photo", 0, 1, item=one[0])


def test_mpv_argv_starts_at_pressed_post():
    calls = []
    video.run_mpv(None, Config(video_vo="tct"), run=lambda a, **k: calls.append(a), which=lambda n: "/usr/bin/mpv",
                  size=(90, 25), tty=None, posts=posts(), start_n=5)
    a = calls[0]
    assert "--playlist-start=3" in a and len(a[a.index("--") + 1:]) == 5


def drive(events, on_like, start=0):
    """Feed mpv-like IPC events through ipc_loop with a real painter; returns (painter, painted lines)."""
    ours, theirs = socket.socketpair()
    out = []
    items = video.posts_playlist(posts())
    liked = set()
    painter = video.StatusPainter(items, 120, 30, write=out.append, start=start,
                                  liked=lambda it=None: bool(it) and it["post_id"] in liked)
    def like(it):
        r = on_like(it); liked.add(it["post_id"]); return r
    t = threading.Thread(target=video.ipc_loop, args=(ours, like, 0), kwargs={"painter": painter}, daemon=True)
    t.start()
    f = theirs.makefile("rb")
    for _ in video.OBSERVE:
        f.readline()
    for ev in events:
        theirs.sendall((json.dumps(ev) + "\n").encode()); time.sleep(0.05)
    time.sleep(0.1)
    theirs.shutdown(socket.SHUT_RDWR); theirs.close(); t.join(2)
    return painter, out


POS = lambda p: {"event": "property-change", "name": "playlist-pos", "data": p}
LIKE = {"event": "client-message", "args": ["xbot-like"]}


def test_crossing_forward_and_back_likes_post_on_screen():
    likes = []
    painter, out = drive([POS(1), POS(2), LIKE, POS(3), POS(2), POS(1), LIKE, POS(-1)],
                         lambda it: (likes.append(it["n"]), f"liked #{it['n']}")[1])
    assert likes == [3, 1]  # D past post 1 into post 3 (post 2 has no media), then A back into post 1
    assert any("post 2/3  ·  @s3" in l for l in out) and any("post 3/3  ·  @s5" in l for l in out)
    assert painter.current()["n"] == 1  # -1 at teardown keeps the last real position
    assert any("♥ liked #3" in l for l in out)


async def test_card_follows_last_viewed_post_and_like_targets_it(mk, monkeypatch):
    b = mk(xonly=True, search=[p for _, p in posts()], **S()); b.tick()
    b.video_forbidden = lambda url: False
    liked_calls = []
    b.like_post = lambda n: (liked_calls.append(n), (True, f"liked #{n}"))[1]
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/mpv")
    def fake_run_mpv(url, cfg, run=None, which=None, posts=None, start_n=None, state=None, on_like=None, liked=None, **k):
        items = video.posts_playlist(posts)
        assert items[video.start_index(items, start_n)]["n"] == start_n
        state["last"] = items[-1]  # pressed D until the last post with media
        on_like(items[-1]); on_like(items[-1])  # like-once per post
        assert liked(items[-1]) and not liked(items[0])
        return "mpv"
    monkeypatch.setattr(video, "run_mpv", fake_run_mpv)
    app = XBotApp(bot=b, autostart=False)
    app.suspend = contextlib.nullcontext
    async with app.run_test(size=(120, 40)) as pilot:
        order = b.nav_order()
        first = next(k for k in order if b.found_post(k).get("media") and b.found_post(k)["media"][0].get("url"))
        app.action_show_post(first); await pilot.pause()
        await pilot.press("v"); await pilot.pause()
        card = app.screen
        last_n = [k for k in order if any(m.get("url") for m in b.found_post(k).get("media") or [])][-1]
        assert isinstance(card, PostCard) and card.n == last_n
        assert liked_calls == [last_n] and b.state.liked == [str(b.found_post(last_n)["id"])]
        b.stopped = True


async def test_like_rolls_back_for_crossed_post(mk, monkeypatch):
    b = mk(xonly=True, search=[p for _, p in posts()], **S()); b.tick()
    b.like_post = lambda n: (False, "like not sent: X rate limit (429)")
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/mpv")
    got = []
    def fake_run_mpv(url, cfg, posts=None, start_n=None, state=None, on_like=None, **k):
        items = video.posts_playlist(posts); got.append(on_like(items[-1])); state["last"] = items[0]
        return "mpv"
    monkeypatch.setattr(video, "run_mpv", fake_run_mpv)
    app = XBotApp(bot=b, autostart=False)
    app.suspend = contextlib.nullcontext
    async with app.run_test(size=(120, 40)) as pilot:
        n0 = next(k for k in b.nav_order() if (b.found_post(k).get("media") or [{}])[0].get("url"))
        app.action_show_post(n0); await pilot.pause()
        await pilot.press("v"); await pilot.pause()
        assert got == ["like not sent: X rate limit (429)"] and b.state.liked == [] and app.screen.n == n0
        b.stopped = True


def test_search_cli_play_crosses_results(monkeypatch):
    class X:
        def search_recent(self, q, n):
            return [p for _, p in posts()]
    played = []
    monkeypatch.setattr(video, "url_forbidden", lambda u: False)
    assert search_cli(["q", "--play", "2"], x=X(), cfg=Config(), out=lambda *_: None,
                      play=lambda argv, **k: played.append(argv), which=lambda n: "/usr/bin/mpv") == 0
    a = played[0]
    assert "--playlist-start=2" in a and len(a[a.index("--") + 1:]) == 5  # all results' media, opens at result 2
