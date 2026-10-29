import asyncio, threading, time
from xbot.app import XBotApp
from tests.test_search import P, S


async def test_f5_tick_runs_off_event_loop(mk):
    """F5 used to run bot.tick (X + Grok sync HTTP) on the UI thread, freezing the TUI."""
    b = mk(xonly=True, search=[P(1)], **S(search_every_n_ticks=1))
    main = threading.get_ident()
    seen, release = {}, threading.Event()
    real = b.tick

    def slow_tick(*a, **k):
        seen["thread"] = threading.get_ident()
        release.wait(5)
        return real(*a, **k)
    b.tick = slow_tick
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test() as pilot:
        t0 = time.monotonic()
        app.action_tick(); await pilot.pause()
        app.action_tick()  # second press while running: ignored, no deadlock
        assert time.monotonic() - t0 < 2  # UI still responsive
        await asyncio.sleep(0.2)
        assert seen.get("thread") not in (None, main)
        release.set()
        for _ in range(50):
            if not getattr(app, "_tick_running", False):
                break
            await asyncio.sleep(0.1)
        assert not app._tick_running and b.ticks >= 1
        await pilot.press("ctrl+c")


async def test_thread_log_events_write_widgets_on_loop_thread(mk):
    """bot.log.event from the F5/credits worker threads must not touch widgets off the Textual thread."""
    b = mk(xonly=True, search=[P(1)], **S(search_every_n_ticks=1))
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test() as pilot:
        main = threading.get_ident()
        writers = []
        for w in (app._console_log, app._feed_log):
            orig = w.write
            w.write = (lambda o: lambda *a, **k: (writers.append(threading.get_ident()), o(*a, **k))[1])(orig)
        await asyncio.to_thread(b.log.event, "warn", "from a worker thread")
        app.action_tick(); await app.workers.wait_for_complete(); await pilot.pause()
        assert writers and set(writers) == {main}
        await pilot.press("ctrl+c")
