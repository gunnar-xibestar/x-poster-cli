"""Open a URL in the user's browser, WSL2-aware, without blocking the UI.

Never hand a URL to explorer.exe: with a query string (`&`, `%`) it falls back to opening
the Documents folder in File Explorer instead of the browser.
"""
import os, shutil, subprocess, threading, webbrowser


def is_wsl():
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def ps_quote(url):
    """PowerShell single-quoted literal ('' escapes a quote)."""
    return "'" + url.replace("'", "''") + "'"


def cmd_escape(url):
    """Escape cmd.exe metacharacters with ^ so `start` gets the whole URL."""
    for ch in "^&|<>()%!\"":
        url = url.replace(ch, "^" + ch)
    return url


def commands(url, wsl=None):
    """Ordered candidate commands (argv lists) for this platform."""
    wsl = is_wsl() if wsl is None else wsl
    if wsl:
        return [["wslview", url],
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", f"Start-Process {ps_quote(url)}"],
                ["cmd.exe", "/c", "start", "", cmd_escape(url)]]
    return [["xdg-open", url]]


def open_url(url, which=shutil.which, popen=subprocess.Popen, wb=webbrowser.open, wsl=None):
    """Try openers in order. Returns the method name used, or None."""
    if not url.startswith("https://"):
        return None
    for cmd in commands(url, wsl):
        if which(cmd[0]):
            try:
                from .secure import safe_env
                popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, start_new_session=True, env=safe_env())  # no secrets in the child env
                return cmd[0]
            except OSError:
                continue
    try:
        if wb(url):
            return "webbrowser"
    except Exception:
        pass
    return None


def open_url_async(url, done, opener=open_url):
    """Run opener in a daemon thread; call done(method_or_None)."""
    t = threading.Thread(target=lambda: done(opener(url)), daemon=True)
    t.start()
    return t
