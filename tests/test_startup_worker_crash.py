"""11:56 crash: two writers exported found.json through one shared .tmp name, so one
os.replace raised FileNotFoundError and the worker killed the app. 11:39 crash: KeyError text-area--gutter
rendering the queue reply editor after its component styles were cleared."""
import threading
from xbot import app as appmod
from xbot.app import QEdit
from xbot.secure import write_private


def test_concurrent_write_private_never_fails(tmp_path):
    p, errs = tmp_path / "found.json", []
    def go(i):
        try:
            for _ in range(200):
                write_private(p, f"data {i}" * 500)
        except Exception as e:
            errs.append(e)
    ts = [threading.Thread(target=go, args=(i,)) for i in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert not errs and p.read_text().startswith("data ")
    assert not list(tmp_path.glob("*.tmp"))


def test_crash_log_records_worker_traceback(tmp_path, monkeypatch):
    import xbot.config as cfg
    monkeypatch.setattr(cfg, "STATE_DIR", tmp_path)
    from textual.worker import WorkerFailed
    def boom():
        open(tmp_path / "missing" / "x")
    try:
        boom()
    except FileNotFoundError as e:
        wf = WorkerFailed(e)
    line = appmod._crash_log(wf)
    log = (tmp_path / "crash.log").read_text()
    assert "FileNotFoundError" in line and "Traceback" in log and "in boom" in log


def test_qedit_renders_and_survives_cleared_component_styles():
    import asyncio
    from textual.app import App
    class A(App):
        def compose(self):
            yield QEdit("hello reply", id="qedit")
    async def run():
        async with A().run_test() as pilot:
            ed = pilot.app.query_one(QEdit)
            await pilot.pause()
            assert "text-area--gutter" in ed._get_component_classes()
            ed.render_lines(ed.region.reset_offset)
            ed._component_styles.clear()  # what Textual does on removal, before a queued frame renders
            ed.get_component_rich_style("text-area--gutter")  # raised KeyError before the fix
            ed._line_cache.clear() if hasattr(ed, "_line_cache") else None
            ed._theme.apply_css(ed) if getattr(ed, "_theme", None) else None
            ed.render_lines(ed.region.reset_offset)
    asyncio.run(run())
