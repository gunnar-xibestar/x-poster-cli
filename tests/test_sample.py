import os, subprocess, sys
from pathlib import Path


async def test_sample_demo_mode_fake_data_no_network(tmp_path, monkeypatch):
    import xbot.sample as S, xbot.config as C
    monkeypatch.setenv("X_API_KEY", "real-looking-key")
    monkeypatch.setattr(C, "CONFIG_DIR", tmp_path / "realcfg"); monkeypatch.setattr(C, "STATE_DIR", tmp_path / "realstate")
    app = S.demo_app(tmp_path / "demo")
    async with app.run_test(size=(160, 45)) as pilot:
        await pilot.pause(); await pilot.pause()
        b = app.bot
        assert b.found and b.queue.pending() and "DEMO" in app.title
        assert b.dry_x.__class__.__name__ == "DryRunX" and not b.reads_live()
        app.query_one("#queue").focus(); await pilot.press("a"); await pilot.pause()
        assert all(s.get("dry", True) for s in getattr(b.dry_x, "sent", [])) and b.cfg.dry_run
    assert "X_API_KEY" not in os.environ
    assert not (tmp_path / "realcfg").exists() and not (tmp_path / "realstate").exists()


def test_sample_help_and_dev_script(tmp_path):
    repo = Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, "-m", "xbot", "sample", "--help"], capture_output=True, text=True, cwd=repo)
    assert r.returncode == 0 and "demo mode" in r.stdout and "--out" not in r.stdout
    r = subprocess.run([sys.executable, "scripts/screenshots.py", "--help"], capture_output=True, text=True, cwd=repo)
    assert r.returncode == 0 and "--out" in r.stdout
    from xbot.sample import default_out
    assert default_out(tmp_path) == tmp_path / "xbot-screenshots"


async def test_sample_real_video_posts_play_through_mpv_path(tmp_path, monkeypatch):
    import xbot.sample as S
    b2, a = S.VIDEO_SEARCH  # nature timelapse first, upscaled music clip second
    assert b2["id"] == "23" and b2["author_id"] == "a23" and b2["username"] == "timelapse_theo"
    assert a["id"] == "24" and a["author_id"] == "a24" and a["username"] == "upscale_ulla"
    assert "2014989728974794752" in b2["media"][0]["url"] and "1362472236838453253" in a["media"][0]["url"]
    import json
    blob = json.dumps(S.VIDEO_SEARCH)
    assert not any(x in blob for x in ("MIT_CSAIL", "MIT CSAIL", "Lilytran", "Rick", "t.co/"))
    for p in S.VIDEO_SEARCH:
        m = p["media"][0]
        assert m["type"] == "video" and m["url"].startswith("https://video.twimg.com/") and ".mp4" in m["url"]
        assert m["width"] and m["height"] and m["duration_ms"] and m["preview_image_url"].startswith("https://pbs.twimg.com/")
        assert all(v["content_type"] == "video/mp4" for v in m["variants"])
    assert "/480x360/" in a["media"][0]["url"] and "/640x360/" in b2["media"][0]["url"]  # 832 kbps pick
    assert (a["media"][0]["width"], a["media"][0]["height"], a["media"][0]["duration_ms"]) == (960, 720, 18085)
    assert (b2["media"][0]["width"], b2["media"][0]["height"], b2["media"][0]["duration_ms"]) == (1920, 1080, 27027)
    app = S.demo_app(tmp_path / "demo")
    async with app.run_test(size=(160, 45)) as pilot:
        await pilot.pause(); await pilot.pause()
        bot = app.bot
        nums = [i + 1 for i, p in enumerate(bot.found) if p["id"] in ("23", "24")]
        assert len(nums) == 2
        for n in nums:  # no network: forbidden check stubbed
            items = bot.media_items(n, forbidden=lambda u: False)
            assert items and items[0]["url"].startswith("https://video.twimg.com/")
