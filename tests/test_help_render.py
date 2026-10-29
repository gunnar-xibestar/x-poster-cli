import pytest
from rich.text import Text
from xbot.commands import parse, CommandError, COMMANDS
from xbot.help import render_help, render_cmd, INDEX
from xbot.render import feed_text, status_markup
from xbot.app import XBotApp
from tests.test_search import P, S


def test_help_sections_cover_all_commands():
    h = render_help()
    for sec in ("Bot control", "Search & found", "Drafts & approval", "Posting", "Settings & costs", "Keys"):
        assert f"## {sec}" in h
    assert set(INDEX) == COMMANDS
    assert "e.g. /reply #2" in h and "Ctrl+C" in h


def test_help_command_detail_and_suggest(mk):
    assert "#n refers to /found" in render_cmd("reply") and "example:" in render_cmd("/cap")
    assert "did you mean /search" in render_cmd("serch")
    with pytest.raises(CommandError, match="did you mean /approve"): parse("/aprove 1")
    b = mk(); b.handle(parse("/help found")); assert "/found [n|mentions|search]" in b.feed[-1]


def test_markup_in_posts_is_escaped():
    evil = "[bold red]pwn[/] [link=http://x]y[/link] \\[ok]"
    rec = {"ts": "2026-10-24T08:00:00-0700", "kind": "found", "msg": "", "n": 1, "source": "search",
           "author": "[red]bob", "snippet": evil, "tweet_id": "123"}
    t = feed_text(rec)
    assert evil in t.plain and "@[red]bob" in t.plain and t.plain.endswith("[post]") and "https://" not in t.plain
    for k in ("draft", "error", "sent", "help", "warn", "status"):
        assert "[bold red]pwn[/]" in feed_text({"ts": rec["ts"], "kind": k, "msg": evil + " [DRY-SEND]"}).plain


def test_status_markup_colors(mk):
    b = mk(xonly=True)
    m = status_markup(b); Text.from_markup(m)
    assert "[green]send=dry[/]" in m and "grok=off (X-only)" in m
    b.handle(parse("/send live")); assert "[bold white on red]send=LIVE[/]" in status_markup(b)


def test_replay_found_on_startup(mk):
    b = mk(xonly=True, search=[P(i) for i in range(10, 22)], **S(search_max_results=12))
    b.tick(); b.feed.clear()
    b2 = mk(xonly=True)
    recs = []; b2.log.rich_sink = recs.append
    log_before = b2.log.path.read_text()
    assert b2.replay_found() == 12
    found = [r for r in recs if r["kind"] == "found"]
    assert [r["n"] for r in found] == list(range(1, 13)) and all(r["replay"] for r in found)
    assert b2.log.path.read_text() == log_before  # not re-logged


async def test_tui_replays_and_colors(mk):
    b = mk(xonly=True, search=[P(5, text="[b]hi[/b]")], **S()); b.tick()
    b2 = mk(xonly=True)
    app = XBotApp(bot=b2, autostart=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        lines = "\n".join(str(l.text) for l in app.query_one("#feed").lines)
        assert "(replay)" in lines and "[b]hi[/b]" in lines
