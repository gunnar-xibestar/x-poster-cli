"""`xbot sample`: the real interactive TUI in demo mode with fake sample data.

Uses a TemporaryDirectory for config/state/logs/secrets so nothing you do here reaches
your real ~/.config/xbot or ~/.local/state/xbot. No network, nothing is sent. The
README screenshot generator (shots_cli) is a separate dev tool: scripts/screenshots.py.
"""
import asyncio, os, tempfile
from pathlib import Path

from .app import XBotApp, ReplyEditor
from .bot import Bot
from .config import Config
from .llm import FakeLLM
from .log import ActionLog
from .xapi import DryRunX, _media_item

OUT = Path("xbot-screenshots")  # set by run()
SIZE = (180, 45)


def P(i, user, name, text, likes=0, rts=0, replies=0, mins=5, quotes=0, topics=()):
    ann = [{"domain": {"id": "66", "name": d}, "entity": {"id": str(1000 + k), "name": e}} for k, (d, e) in enumerate(topics)]
    return {"context_annotations": ann, "id": str(i), "text": text, "author_id": f"a{i}", "username": user, "name": name,
            "conversation_id": str(i), "created_at": f"2026-10-24T18:{60 - mins:02d}:00.000Z",
            "public_metrics": {"like_count": likes, "retweet_count": rts, "reply_count": replies, "quote_count": quotes}}


MENTIONS = [P(1, "exampleuser", "Example User",
              "@xbot_demo does your CLI support custom keybindings yet? Loving the card view so far.", 12, 1, 3, 4),
            P(2, "maya_codes", "Maya", "@xbot_demo is there a way to export my drafts queue to a file?", 5, 0, 1, 6),
            P(3, "opsdan", "Dan Ops", "@xbot_demo running this on a headless server over ssh and it works great. "
              "Any plans for a config file per account?", 8, 2, 2, 8),
            P(4, "pixelpia", "Pia", "@xbot_demo the topic filter saved my sanity this week, thank you!", 21, 3, 1, 10)]
SEARCH = [
    P(11, "rustacean_ray", "Ray (Rust)", "Rust 1.95 is out! Async closures are finally stable and the compile-time "
      "improvements are very noticeable on our workspace. Upgrade notes in the release blog.", 342, 88, 41, 12, 17,
      [("Interests and Hobbies Category", "Technology"), ("Technology", "Programming languages"), ("Product", "Rust")]),
    P(12, "devjane", "Jane Dev", "Linux 7.2-rc1 landed: new scheduler tweaks, better io_uring perf, and a pile of "
      "Rust driver work. Building it on my laptop tonight.", 210, 45, 19, 25),
    P(13, "llm_tinkerer", "Local LLM Tinkerer", "Running a 14B model fully local on a 3-year-old laptop at 20 tok/s. "
      "Quantization has come a long way. No cloud needed for my coding assistant anymore.", 128, 30, 22, 31),
    P(14, "cli_carla", "Carla", "Hot take: the best CLI tools do one thing, print plain text, and have a --json flag. "
      "What's your favorite small terminal tool this year?", 95, 12, 57, 40),
    P(15, "termfan42", "Terminal Fan", "Just rewrote my dotfiles manager as a tiny TUI with Textual. "
      "Keyboard-first, mouse optional, and it looks great in any terminal.", 64, 9, 8, 52),
    P(18, "gopher_gil", "Gil", "Go 1.27 adds iterator helpers to the standard library. Small change, big quality "
      "of life for everyday code.", 77, 14, 9, 33),
    P(19, "db_dora", "Dora", "SQLite keeps surprising me: we moved our analytics side project to it and queries "
      "got faster, not slower.", 156, 33, 28, 44),
    P(20, "neovim_nate", "Nate", "Finally moved my whole Neovim config to Lua. Startup time is now under 40ms.", 49, 6, 11, 47),
    P(21, "wasm_wren", "Wren", "WebAssembly components are getting real: I shipped a plugin system with them this "
      "weekend and it just worked.", 88, 19, 7, 55),
    P(16, "spammy_sam", "Sam", "Join my telegram now for FREE giveaway click here!!", 1, 0, 0, 7),
    P(17, "hype_bot99", "Hype", "Join my telegram for 100x crypto signals, giveaway now", 0, 0, 0, 9),
]

# Two X posts with real video media (post identity/text are fictional), shaped as returned by the X API (GET /2/tweets, media.fields=type,preview_image_url,variants,
# width,height,duration_ms). Their media goes through xapi._media_item like live search results, so `v` plays the
# real mp4 from video.twimg.com in the mpv viewer.
def _real(pid, author_id, user, name, created, text, metrics, media):
    return {"id": pid, "text": text, "author_id": author_id, "username": user, "name": name, "conversation_id": pid,
            "created_at": created, "public_metrics": metrics, "context_annotations": [],
            "media": [_media_item(m) for m in media]}


VIDEO_SEARCH = [
    _real("23", "a23", "timelapse_theo", "Theo Frames", "2026-10-26T18:05:00.000Z",
          "Weekend project: a Raspberry Pi 5 + cron + ffmpeg timelapse rig. Six months of forest, 27 seconds, "
          "stitched and stabilized fully headless. Script in the replies.",
          {"like_count": 17, "retweet_count": 1, "reply_count": 2, "quote_count": 0},
          [{"media_key": "13_2014989728974794752", "type": "video", "width": 1920, "height": 1080, "duration_ms": 27027,
            "preview_image_url": "https://pbs.twimg.com/amplify_video_thumb/2014989728974794752/img/d3KNwRI8Ai51WH3Z.jpg",
            "variants": [
                {"content_type": "application/x-mpegURL", "url": "https://video.twimg.com/amplify_video/2014989728974794752/pl/dGmJlftahRtFNNSt.m3u8"},
                {"bit_rate": 2176000, "content_type": "video/mp4", "url": "https://video.twimg.com/amplify_video/2014989728974794752/vid/avc1/1280x720/XCHTMAXPiyf2_P2k.mp4"},
                {"bit_rate": 832000, "content_type": "video/mp4", "url": "https://video.twimg.com/amplify_video/2014989728974794752/vid/avc1/640x360/Ubf7wqKJpJ5605il.mp4"},
                {"bit_rate": 10368000, "content_type": "video/mp4", "url": "https://video.twimg.com/amplify_video/2014989728974794752/vid/avc1/1920x1080/dcwCVOEGbb4sR9pP.mp4"},
                {"bit_rate": 256000, "content_type": "video/mp4", "url": "https://video.twimg.com/amplify_video/2014989728974794752/vid/avc1/480x270/jPhtqzJtSMp1qKQK.mp4"}]}]),
    _real("24", "a24", "upscale_ulla", "Ulla (ML video)", "2026-10-26T18:20:00.000Z",
          "Tried our new open-source video upscaler on a classic 2000s music clip: 240p in, crisp 4K out, 18 s per clip "
          "on one GPU. Weights + demo notebook dropping Friday.",
          {"like_count": 36963, "retweet_count": 6185, "reply_count": 546, "quote_count": 1214},
          [{"media_key": "7_1362472236838453253", "type": "video", "width": 960, "height": 720, "duration_ms": 18085,
            "preview_image_url": "https://pbs.twimg.com/ext_tw_video_thumb/1362472236838453253/pu/img/dktRs8iYqQS_DLrn.jpg",
            "variants": [
                {"bit_rate": 256000, "content_type": "video/mp4", "url": "https://video.twimg.com/ext_tw_video/1362472236838453253/pu/vid/360x270/8YA9cKg5e7Xt0GOk.mp4?tag=10"},
                {"bit_rate": 832000, "content_type": "video/mp4", "url": "https://video.twimg.com/ext_tw_video/1362472236838453253/pu/vid/480x360/FV9rvLxDdAVBUwqw.mp4?tag=10"},
                {"bit_rate": 2176000, "content_type": "video/mp4", "url": "https://video.twimg.com/ext_tw_video/1362472236838453253/pu/vid/960x720/p2-9yg-dfrn82oSX.mp4?tag=10"},
                {"content_type": "application/x-mpegURL", "url": "https://video.twimg.com/ext_tw_video/1362472236838453253/pu/pl/uJtTAice3581_sdE.m3u8?tag=10&v=425"}]}]),
]
DRAFTS = ["Congrats on the release! Async closures were the one I was waiting for.",
          "Nice. Curious how the io_uring changes affect latency on desktop workloads.",
          "Impressive speed. Which quant format are you using?",
          "Yes on --json. ripgrep and jq are still my daily drivers.",
          "Textual is great for this. Do you ship it as a single binary?",
          "Not yet, but custom keybindings are on the roadmap. Thanks for trying it!"]
MENTION_DRAFTS = ["Not yet, but custom keybindings are on the roadmap. Thanks for trying it!",
                  "Yes! /queue export writes your drafts to JSON. Happy to add CSV if useful.",
                  "Glad it works well over ssh. Per-account config files are next on the list.",
                  "That makes my week. Thanks for the kind words!"]

CARD_DRAFT = ("Async closures landing stable is huge. Did you see a noticeable drop in build times after upgrading, "
              "or mostly ergonomics wins so far?")


def make_bot(tmp):
    cfg = Config(post_every_n_ticks=0, search_every_n_ticks=1)
    feed = []
    log = ActionLog(Path(tmp), sink=feed.append)
    b = Bot(cfg, None, DryRunX(list(MENTIONS), list(SEARCH)), log)
    b.author_fetch = lambda tid: None
    b.feed = feed
    return b


async def shoot(app, pilot, name):
    await pilot.pause(); await asyncio.sleep(0.3); await pilot.pause()
    app.save_screenshot(f"{name}.svg", path=str(OUT))
    print("wrote", name)


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        b = make_bot(tmp)
        app = XBotApp(bot=b, autostart=False)
        async with app.run_test(size=SIZE) as pilot:
            app._run("/tick"); await pilot.pause()
            b.llm = FakeLLM([DRAFTS[-1]] * 3)  # turn on (fake) Grok drafting after the fetch
            ments = [p for p in b.found if p.get("source") == "mention"]
            for d, p in zip(MENTION_DRAFTS, ments):  # Grok drafts for mentions in the side panel
                b.queue.add("reply", d, in_reply_to=p["id"], context=f"@{p['username']}: {p['text']}", source="mention")
            rust = next(i + 1 for i, p in enumerate(b.found) if p["id"] == "11")
            app._run("/status")
            cmd = app.query_one("#cmd")
            cmd.value = "/filter"; app.query_one("#feed").focus()  # sample command, input unfocused (no cursor)
            await shoot(app, pilot, "02-main")
            cmd.value = ""
            app._run(f"/show {rust}"); await shoot(app, pilot, "04-post-selection")  # card over the main feed
            b.llm = FakeLLM([CARD_DRAFT] * 5); await pilot.press("g"); await asyncio.sleep(0.5)
            ed = app.screen.query_one("#ed"); ed.cursor_blink = False; ed.move_cursor(ed.document.end); ed.blur()
            await shoot(app, pilot, "06-auto-reply")  # Grok draft
            await pilot.press("escape"); await pilot.pause()
            while len(app.screen_stack) > 1: app.pop_screen()
            await pilot.pause(); app.query_one("#feed").focus(); await pilot.pause()
            app._run("/filter hide @spammy_sam"); await pilot.pause()
            app._run("/filter"); await pilot.pause()
            app._run("/filter edit"); await shoot(app, pilot, "08-topic-picker")
            await pilot.press("escape"); await pilot.pause()
            app._run("/hidden"); await shoot(app, pilot, "10-hidden")
            await pilot.press("escape"); await pilot.pause()
            while len(app.screen_stack) > 1: app.pop_screen()
            b.cfg.filtered_mentioners = ["spammy_sam", "promo_pete", "airdrop_andy"]
            app._run("/filter mentioners"); await pilot.pause()
            await pilot.press("down"); await pilot.press("space"); await pilot.press("tab")
            await pilot.press(*"@reply_guy_rex"); await shoot(app, pilot, "09-mentioners")
            await pilot.press("escape"); await pilot.pause()
            while len(app.screen_stack) > 1: app.pop_screen()
            cmd.remember("/filter hide war"); cmd.remember("/show 5")
            cmd.focus(); cmd.value = "/sea"; cmd.action_complete(); await pilot.pause()
            cmd.cursor_blink = False
            await shoot(app, pilot, "03-tab-complete")
            cmd.value = ""; app.query_one("#feed").focus()
            app._run(f"/show {rust}"); await pilot.pause()
            await pilot.press("h"); await pilot.pause(); await pilot.press("y"); await pilot.pause()
            await pilot.press("down"); await pilot.press("space")
            await shoot(app, pilot, "05-hide-filters")
            while len(app.screen_stack) > 1: app.pop_screen()
    with tempfile.TemporaryDirectory() as tmp2:  # fresh state dir: empty queue, no prior log
        os.chdir(tmp2)
        await startup_shot(tmp2)
    to_png(sorted(OUT.glob("*.svg")))


EXTRA_MENTION = P(5, "quiet_quinn", "Quinn", "@xbot_demo does it ever post without asking? Want to try it safely.", 3, 0, 1, 11)
EXTRA_SEARCH = P(22, "shell_sasha", "Sasha", "fzf + ripgrep + a tiny shell function = the fastest project switcher I've ever used.", 71, 10, 6, 58)
STARTUP_MENTION_DRAFTS = MENTION_DRAFTS + ["Never: every post and reply waits for your approval."]
STARTUP_SEARCH_DRAFTS = DRAFTS[:5] + [
    "Iterator helpers are such a nice quality-of-life win.",
    "Same experience here. SQLite is wildly underrated for side projects.",
    "Under 40ms is impressive. Lazy-loading plugins?",
    "Components for plugins is a great fit. Which runtime did you use?",
    "Stealing this. Do you share the function in your dotfiles?"]


async def startup_shot(tmp):
    """04: what a user sees on opening the app - mentions, suggested posts, and Grok drafts queued for each."""
    cfg = Config(post_every_n_ticks=0, search_every_n_ticks=1)
    log = ActionLog(Path(tmp), sink=[].append)
    b = Bot(cfg, None, DryRunX(MENTIONS + [EXTRA_MENTION], SEARCH[:9] + [EXTRA_SEARCH] + SEARCH[9:]), log)
    b.author_fetch = lambda tid: None
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(180, 58)) as pilot:
        app._run("/tick"); await pilot.pause()
        b.queue.items.clear()
        ments = [p for p in b.found if p.get("source") == "mention"]
        search = [p for p in b.found if p.get("source") == "search" and p["username"] not in ("spammy_sam", "hype_bot99")]
        for d, p in list(zip(STARTUP_MENTION_DRAFTS, ments)) + list(zip(STARTUP_SEARCH_DRAFTS, search)):
            b.queue.add("reply", d, in_reply_to=p["id"], context=f"@{p['username']}: {p['text']}", source=p["source"])
        app._run("/status")
        app.query_one("#cmd").value = ""; app.query_one("#feed").focus()
        await shoot(app, pilot, "01-startup")


def to_png(svgs):
    """Convert SVG -> PNG with cairosvg if installed (pip install cairosvg); otherwise keep the SVGs."""
    try:
        import cairosvg
    except ImportError:
        print("cairosvg not installed: wrote SVGs only. For PNGs: .venv/bin/pip install cairosvg, then run scripts/screenshots.py again"); return
    for svg in svgs:
        png = svg.with_suffix(".png")
        # Swap emoji metric icons for monochrome symbols so they don't render as missing-glyph boxes.
        src = svg.read_text()
        for emo, sym in (("\U0001f4ac", "\u21a9"), ("\U0001f501", "\u27f2")):
            src = src.replace(emo, sym).replace(f"&#{ord(emo)};", sym).replace(f"&#x{ord(emo):x};", sym)
        try:
            cairosvg.svg2png(bytestring=src.encode(), write_to=str(png), output_width=2000)
        except Exception as e:
            print("PNG conversion skipped for", svg.name, "-", e); continue
        svg.unlink(); print("png", png.name)


def default_out(cwd=None):
    """docs/screenshots inside the x-poster-cli repo, else ./xbot-screenshots."""
    cwd = Path(cwd or os.environ.get("XBOT_CWD") or os.getcwd())
    if (cwd / "xbot" / "sample.py").exists() and (cwd / "docs").is_dir():
        return cwd / "docs" / "screenshots"
    return cwd / "xbot-screenshots"


def run(out=None):
    """Write the sample screenshots to `out` (fake data, temp state, no network, no keys). Returns the files."""
    global OUT
    for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET", "XAI_API_KEY"):
        os.environ.pop(k, None)
    base = Path(os.environ.get("XBOT_CWD") or os.getcwd())
    OUT = (base / out) if out and not Path(out).is_absolute() else Path(out) if out else default_out(base)
    OUT = OUT.resolve()
    prev = os.getcwd()
    try:
        asyncio.run(main())
    finally:
        os.chdir(prev)
    files = sorted(OUT.glob("*.png")) + sorted(OUT.glob("*.svg"))
    print(f"wrote {len(files)} file(s) to {OUT}")
    return files


_SANDBOX_ENV = ("XBOT_CONFIG_DIR", "XBOT_STATE_DIR")


def sandbox(tmp):
    """Point every config/state path (config.json, env/secrets, tokens.json, state.json, actions log, crash.log,
    mpv-stderr.log, history) at `tmp` for the demo. Returns a restore() callable."""
    from . import config as C, log as L
    tmp = Path(tmp)
    cdir, sdir = tmp / "config", tmp / "state"
    cdir.mkdir(parents=True, exist_ok=True); sdir.mkdir(parents=True, exist_ok=True)
    old = (C.CONFIG_DIR, C.STATE_DIR, L.STATE_DIR, {k: os.environ.get(k) for k in _SANDBOX_ENV})
    C.CONFIG_DIR, C.STATE_DIR, L.STATE_DIR = cdir, sdir, sdir
    os.environ["XBOT_CONFIG_DIR"], os.environ["XBOT_STATE_DIR"] = str(cdir), str(sdir)

    def restore():
        C.CONFIG_DIR, C.STATE_DIR, L.STATE_DIR = old[0], old[1], old[2]
        for k, v in old[3].items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return restore


def demo_app(tmp):
    """XBotApp over fake data in `tmp`: DryRunX, fake Grok, no keys, no browser, real config/state untouched.
    Every write path (config saves are no-ops; state, logs, crash.log, tokens, secrets paths) goes to `tmp`."""
    restore = sandbox(tmp)
    for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET", "XAI_API_KEY", "X_BEARER_TOKEN"):
        os.environ.pop(k, None)
    cfg = Config(post_every_n_ticks=0, search_every_n_ticks=1, dry_run=True, reads_live=False, oembed_prefetch=False)
    log = ActionLog(Path(tmp))
    b = Bot(cfg, None, DryRunX(MENTIONS + [EXTRA_MENTION], VIDEO_SEARCH + SEARCH[:9] + [EXTRA_SEARCH] + SEARCH[9:]), log,
            state_dir=Path(tmp), save_config=lambda: None, real_x_factory=None)
    b.author_fetch = lambda tid: None
    b.opener = lambda url, done: (log.event("info", f"[demo] would open {url}"), done("demo"))
    b.demo = True
    app = DemoApp(bot=b, autostart=False)
    app._restore_sandbox = restore
    return app


class DemoApp(XBotApp):
    _restore_sandbox = None

    def on_unmount(self):
        if self._restore_sandbox:
            self._restore_sandbox(); self._restore_sandbox = None
    def on_mount(self):
        self.call_later(self._demo_setup)  # after XBotApp.on_mount wired the log sinks

    def _demo_setup(self):
        b = self.bot
        self.title = "xbot DEMO (fake data, nothing is sent)"
        b.tick(True)
        ments = [p for p in b.found if p.get("source") == "mention"]
        search = [p for p in b.found if p.get("source") == "search" and p["username"] not in ("spammy_sam", "hype_bot99")]
        for d, p in list(zip(STARTUP_MENTION_DRAFTS, ments))[:4] + list(zip(STARTUP_SEARCH_DRAFTS, search))[:4]:
            b.queue.add("reply", d, in_reply_to=p["id"], context=f"@{p['username']}: {p['text']}", source=p["source"])
        b.llm = FakeLLM(STARTUP_SEARCH_DRAFTS + [CARD_DRAFT])  # fake Grok for g / F5
        b.log.event("ctl", "DEMO mode: fake posts and drafts, temp state, no network, nothing is sent. Ctrl+Q quits.")
        self.refresh_ui()


def cli(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="xbot sample",
                                 description="Open the xbot TUI in demo mode with fake sample data "
                                             "(no network, nothing sent, your config/state untouched).")
    ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        demo_app(tmp).run()
    return 0


def shots_cli(argv):
    """Dev only (scripts/screenshots.py): write README screenshots."""
    import argparse
    ap = argparse.ArgumentParser(prog="scripts/screenshots.py",
                                 description="Generate sample screenshots of the xbot TUI (fake data, no network, no keys).")
    ap.add_argument("--out", metavar="DIR", help="output folder (default: docs/screenshots in the repo, else ./xbot-screenshots)")
    a = ap.parse_args(argv)
    run(a.out)
    return 0
