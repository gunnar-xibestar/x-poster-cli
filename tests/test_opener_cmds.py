from xbot.opener import commands, cmd_escape, ps_quote, open_url

URL = "https://x.com/intent/post?in_reply_to=123&text=hi%20there%20it's%20me"


def test_wsl_order_never_explorer():
    cmds = commands(URL, wsl=True)
    assert [c[0] for c in cmds] == ["wslview", "powershell.exe", "cmd.exe"]
    assert not any("explorer" in a for c in cmds for a in c)
    assert cmds[0] == ["wslview", URL]


def test_powershell_quoting_keeps_whole_url():
    c = commands(URL, wsl=True)[1]
    assert c[:4] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]
    assert c[4] == "Start-Process 'https://x.com/intent/post?in_reply_to=123&text=hi%20there%20it''s%20me'"
    assert ps_quote("a'b") == "'a''b'"


def test_cmd_escapes_ampersand_and_percent():
    c = commands(URL, wsl=True)[2]
    assert c[:4] == ["cmd.exe", "/c", "start", ""]
    assert "^&text=" in c[4] and "^%20" in c[4] and "&text" not in c[4].replace("^&", "")
    assert cmd_escape("a&b|c") == "a^&b^|c"


def test_linux_uses_xdg_open_then_webbrowser():
    assert commands(URL, wsl=False) == [["xdg-open", URL]]
    assert open_url(URL, which=lambda c: False, wb=lambda u: True, wsl=False) == "webbrowser"


def test_wsl_without_wslview_picks_powershell():
    calls = []
    have = {"powershell.exe", "cmd.exe", "explorer.exe", "xdg-open"}
    m = open_url(URL, which=lambda c: c in have, popen=lambda c, **k: calls.append(c), wsl=True)
    assert m == "powershell.exe" and URL.replace("'", "''") in calls[0][4]
