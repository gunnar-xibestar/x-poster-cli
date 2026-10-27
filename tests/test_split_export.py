import json
from xbot.commands import parse
from xbot.xapi import DryRunX
from tests.test_search import P, S

KEYS = {"X_API_KEY": "kkkkk1", "X_API_SECRET": "sssss2", "X_ACCESS_TOKEN": "ttttt3", "X_ACCESS_TOKEN_SECRET": "uuuuu4"}


class FakeReal(DryRunX):
    """Stands in for RealX: reads return posts, sends recorded."""


def test_reads_auto_live_with_keys_sends_stay_dry(mk, monkeypatch):
    for k, v in KEYS.items(): monkeypatch.setenv(k, v)
    real = FakeReal(fake_search=[P(1)])
    b = mk(xonly=True, **S()); b.real_x_factory = lambda: real
    assert b.reads_live() and b.cfg.dry_run
    b.tick()
    assert real.searches and len(b.found) == 1
    assert b.state.spent_today() == 0.005  # 1 search result read
    opened = []; b.opener = lambda url, done: (opened.append(url), done("test"))
    b.handle(parse("/reply #1 nice")); b.handle(parse(f"/approve @{b.queue.pending()[0].id}"))
    # non-mention reply: opens X's prefilled reply page, nothing sent through the API, no spend
    assert real.sent == [] and b.dry_x.sent == [] and b.state.spent_today() == 0.005
    assert opened == ["https://x.com/intent/post?in_reply_to=1&text=nice"] and b.found[0]["replied"]
    st = b.status(); assert "reads=live" in st and "send=dry" in st


def test_reads_default_off_without_keys_and_commands(mk):
    b = mk(xonly=True, **S())
    assert not b.reads_live() and "reads=off" in b.status()
    b.handle(parse("/reads live")); assert b.reads_live()
    b.handle(parse("/reads off")); assert not b.reads_live()
    b.handle(parse("/send live")); assert not b.cfg.dry_run and "send=LIVE" in b.status()
    b.handle(parse("/send dry")); assert b.cfg.dry_run
    b.handle(parse("/dryrun off")); assert not b.cfg.dry_run


def test_found_export(mk, monkeypatch):
    for k, v in KEYS.items(): monkeypatch.setenv(k, v)
    monkeypatch.setenv("XAI_API_KEY", "xai-secret-zzz")
    b = mk(xonly=True, search=[P(7, text="Linux 7 is out"), P(8)], **S(reads_live=False))
    b.tick()
    data = json.loads(b.found_path.read_text())
    assert [p["n"] for p in data["posts"]] == [1, 2]
    p = data["posts"][0]
    assert set(p) == {"n", "id", "author", "text", "created_at", "url", "source", "replied", "name", "public_metrics", "tags", "xlabels", "username", "author_id", "author_lookup"}
    assert p["url"] == "https://x.com/i/status/7" and p["author"] == "ua1" and p["replied"] is False
    b.handle(parse("/reply #1 cool")); b.handle(parse(f"/approve @{b.queue.pending()[0].id}"))
    assert json.loads(b.found_path.read_text())["posts"][0]["replied"] is True
    raw = b.found_path.read_text()
    assert not any(v in raw for v in list(KEYS.values()) + ["xai-secret-zzz"])
    assert not b.found_path.with_suffix(".tmp").exists()
    b.found_path.unlink(); b.handle(parse("/export")); assert b.found_path.exists()
    b2 = mk(xonly=True); assert len(b2.found) == 2 and b2.found[0]["replied"]
