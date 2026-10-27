from xbot.commands import parse
from test_search import P, S


def test_backfill_triggers_with_until_id_oldest(mk):
    b = mk(xonly=True, search=[P(50), P(51)], **S())
    b.tick()  # first search: 2 posts, oldest=50; backfill finds nothing older
    assert b.search_oldest_id == "50"
    assert any("no older posts left" in f for f in b.feed)
    b.dry_x.fake_search = [P(52), P(10), P(11)]
    b.tick()
    calls = b.dry_x.search_calls
    assert calls[-1] == {"since_id": None, "until_id": "50"}
    ids = {p["id"] for p in b.found}
    assert {"10", "11", "52"} <= ids and b.search_oldest_id == "10"
    assert any("· 2 older" in f for f in b.feed)


def test_backfill_not_triggered_when_enough(mk):
    b = mk(xonly=True, search=[P(i) for i in range(100, 110)], **S())
    b.tick()
    assert all(c["until_id"] is None for c in b.dry_x.search_calls)


def test_backfill_toggle_off(mk):
    b = mk(xonly=True, search=[P(50)], **S())
    b.handle(parse("/backfill off")); assert not b.cfg.search_backfill
    b.dry_x.fake_search = [P(50), P(10)]
    b.tick(); b.tick()
    assert all(c["until_id"] is None for c in b.dry_x.search_calls)
    b.handle(parse("/backfill on")); assert b.cfg.search_backfill


def test_filter_view_lines_short_and_indented():
    from rich.text import Text
    from xbot.render import feed_markup
    rec = {"kind": "filter", "ts": "2026-10-24T12:00:00", "msg": "", "on": True,
           "topics_on": ["adult", "spam", "x-flags"], "topics_off": ["war", "politics", "crime", "disaster", "celebrity", "sports", "crypto-shill"],
           "words": ["promoted posts"], "tags": ["nsfw"], "mentioners": ["spammy_sam"],
           "skipped": ["promoted posts", "nsfw", "onlyfans", "porn", "ai girlfriend", "rug pull", "giveaway", "airdrop"]}
    lines = Text.from_markup(feed_markup(rec)).plain.split("\n")
    assert all(len(l) <= 80 for l in lines), [l for l in lines if len(l) > 80]
    assert all(l == "" or l.startswith("  ") for l in lines[1:])
    assert any(l.strip().startswith("remove /filter show layoffs") for l in lines)
