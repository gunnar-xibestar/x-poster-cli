"""Small text helpers used across the TUI.

clean() strips zero-width / variation-selector chars that make terminals draw emoji
wider than Rich measures (which would push text past the panel edge). clip() shortens
a string for feed snippets without cutting mid-word when possible.
"""
import re

# Variation selectors / zero-width joiners make terminals draw emoji wider than Rich measures,
# which pushes text past the panel edge. Drop them for display.
_ZW = re.compile("[\ufe0e\ufe0f\u200b-\u200f\u2060\U000e0000-\U000e007f]")


def clean(s):
    return _ZW.sub("", s or "")


def clip(s, n):
    """One line, at most n chars; ends with an ellipsis if cut."""
    s = " ".join(clean(s).split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "\u2026"
