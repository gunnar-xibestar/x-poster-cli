from xbot.textutil import clip
def test_clip():
    assert clip("short", 10) == "short"
    assert clip("a b\nc", 10) == "a b c"
    assert clip("x" * 20, 10) == "x" * 9 + "\u2026"
