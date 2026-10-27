from urllib.parse import urlparse, parse_qs
from xbot.commands import parse
from xbot.bot import share_url, SHARE_TEXT


def test_share_url_encoding():
    u = share_url()
    assert u.startswith("https://x.com/intent/post?text=") and " " not in u and "%3A%2F%2Fgithub.com" in u
    assert parse_qs(urlparse(u).query)["text"] == [SHARE_TEXT]
    assert SHARE_TEXT.endswith("https://github.com/gunnar-xibestar/x-poster-cli")
    assert share_url("a&b c") == "https://x.com/intent/post?text=a%26b%20c"


def test_share_opens_browser_no_api(mk):
    b = mk()
    opened = []
    b.opener = lambda url, done: (opened.append(url), done("wslview"))
    def boom(*a, **k): raise AssertionError("API used")
    b.dry_x.post = boom
    b.handle(parse("/share"))
    assert opened == [share_url()] and b.dry_x.sent == []
    assert sum("share post" in l for l in b.feed) == 1


def test_share_in_completion_and_help():
    from xbot.commands import COMMANDS
    import xbot.help as H
    assert "/share" in __import__('inspect').getsource(H)
    assert "share" in COMMANDS
