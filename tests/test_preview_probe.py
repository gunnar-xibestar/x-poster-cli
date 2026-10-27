import sys
from PIL import Image as PILImage
from xbot.app import XBotApp, PostCard, FilterOptions
from tests.test_search import S
from tests.test_media_layout import P


def test_main_probes_before_textual(monkeypatch):
    import xbot.app as A
    order = []
    monkeypatch.setattr(A, "probe_graphics", lambda: order.append("probe"))
    class FakeApp:
        def __init__(self): order.append("app")
        def run(self): order.append("run")
        def shutdown(self): pass
    monkeypatch.setattr(A, "XBotApp", FakeApp)
    monkeypatch.setattr("xbot.secure.env_file_problem", lambda p: None)
    A.main([])
    assert order[:3] == ["probe", "app", "run"]


def test_auto_renderer_respects_probe(monkeypatch):
    import xbot.app as A
    class Caps: sixel = False
    monkeypatch.setattr(A, "graphics_probed", lambda: Caps())
    monkeypatch.setenv("WT_SESSION", "1"); monkeypatch.delenv("TMUX", raising=False)
    assert A.pick_renderer("auto") == "halfblock"
    Caps.sixel = True
    assert A.pick_renderer("auto") == "sixel"
