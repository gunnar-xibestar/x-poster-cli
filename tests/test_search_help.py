from xbot.commands import parse
from xbot import search_history as sh
from xbot.help import render_cmd, SEARCH_TIPS
from tests.test_search import P, S


def test_search_help_shows_tips_without_changing_query(mk):
    b = mk(xonly=True, search=[P(1)], **S())
    q = b.cfg.search_query
    for line in ("/search help", "/search", "/search ?", "/search HELP"):
        b.handle(parse(line))
    assert b.cfg.search_query == q and b.dry_x.searches == [] and sh.load(b.state_dir) == []
    for op in ("OR", "-is:retweet", "has:video_link", "lang:en", "from:", "is:verified", "#rustlang", "min_likes:", "billed"):
        assert op in SEARCH_TIPS
    assert "has:videos" not in SEARCH_TIPS and "min_faves" in SEARCH_TIPS  # only as "rejected" warning
    assert SEARCH_TIPS in render_cmd("search")
    b.handle(parse("/search rust lang:en")); assert b.cfg.search_query == "rust lang:en"
