import pytest
from PIL import Image as PILImage
from rich.console import Console
from xbot.app import XBotApp, FoundPicker
from xbot.render import card_renderable
from tests.test_search import S
from tests.test_media_layout import P


def text_lines(renderable, width):
    import io
    c = Console(file=io.StringIO(), width=width, height=200, record=True, color_system=None, _environ={})
    c.print(renderable)
    return c.export_text().splitlines()


@pytest.mark.parametrize("w,media", [(120, False), (120, True), (180, False), (180, True)])
async def test_card_text_fills_container_width(mk, monkeypatch, w, media):
    import xbot.app as A
    b = mk(xonly=True, search=[P(1, "a " * 900)], **S()); b.tick()
    if media:
        b.found[0]["media"] = [{"type": "photo", "url": "https://pbs.twimg.com/a.jpg", "width": 1600, "height": 900}]
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(w, 45)) as pilot:
        app.action_show_post(1); await pilot.pause()
        s = app.screen
        sc, card = s.query_one("#card-scroll"), s.query_one("#card")
        assert card.region.width >= sc.content_region.width - 2  # only the scrollbar may sit beside it
        lines = [l for l in text_lines(card_renderable(1, b.found[0], b), card.region.width) if "a a a a" in l]
        assert lines and max(len(l.rstrip(" │")) for l in lines) >= card.region.width - 4  # text runs to the right edge
        b.stopped = True


@pytest.mark.parametrize("w", [120, 180])
async def test_found_view_layout(mk, w):
    b = mk(xonly=True, search=[P(i, "long text " * 40) for i in range(1, 4)], **S()); b.tick()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(w, 40)) as pilot:
        app.push_screen(FoundPicker(list(enumerate(b.found, 1)))); await pilot.pause()
        lv = app.screen.query_one("#picker")
        assert lv.region.right <= w and lv.region.width >= min(int(w * 0.9) - 1, 160) - 1
        assert str(lv.border_title).startswith("[bold bright_red]esc[/bold bright_red] to back") and lv.styles.border_title_align == "left"
        from textual.widgets import Label
        for lab in app.screen.query(Label):
            assert lab.region.width >= lv.content_region.width - 4  # labels fill the list width (wrap, no clipping)
            assert lab.region.right <= lv.region.right
        b.stopped = True


async def test_v_failure_logs_and_keeps_running(mk, monkeypatch, tmp_path):
    import xbot.config as C
    monkeypatch.setattr(C, "STATE_DIR", tmp_path)
    b = mk(xonly=True, search=[P(1, "pic")], **S()); b.tick()
    b.found[0]["media"] = [{"type": "photo", "url": "https://pbs.twimg.com/a.jpg"}]
    from xbot import video
    import contextlib
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/mpv")
    def boom(*a, **k): raise RuntimeError("mpv exploded")
    monkeypatch.setattr(video, "run_mpv", boom)
    b.media_items = lambda n: (_ for _ in ()).throw(RuntimeError("lookup exploded"))
    app = XBotApp(bot=b, autostart=False)
    app.suspend = contextlib.nullcontext
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_post(1); await pilot.pause()
        await pilot.press("v"); await pilot.pause()
        assert app.is_running and "lookup exploded" in (tmp_path / "crash.log").read_text()
        assert "media viewer failed (RuntimeError)" in b.log.path.read_text()
        b.stopped = True


async def test_video_head_check_error_not_fatal(mk, monkeypatch, tmp_path):
    import xbot.config as C
    from xbot import video
    monkeypatch.setattr(C, "STATE_DIR", tmp_path)
    b = mk(xonly=True, search=[P(1, "clip")], **S()); b.tick()
    b.found[0]["media"] = [{"type": "video", "url": "https://video.twimg.com/v.mp4"}]
    b.media_items = lambda n: (_ for _ in ()).throw(ValueError("head broke"))
    played = []
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/mpv")
    monkeypatch.setattr(video, "run_mpv", lambda url, cfg, run=None, which=None, **k: played.append(k["posts"][0][1]["media"][0]["url"]))
    app = XBotApp(bot=b, autostart=False)
    import contextlib
    app.suspend = contextlib.nullcontext
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_post(1); await pilot.pause()
        await pilot.press("v"); await pilot.pause()
        assert app.is_running and played == ["https://video.twimg.com/v.mp4"]
        b.stopped = True
