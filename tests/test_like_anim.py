from xbot.app import XBotApp, PostCard
from xbot.state import BotState
from tests.test_search import S
from tests.test_card_open import rich_post


async def test_like_once_heart_every_press(mk):
    b = mk(xonly=True, search=[rich_post(5)], **S()); b.tick()
    opened = []
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(140, 40)) as pilot:
        b.opener = lambda url, done: (opened.append(url), done("test"))
        calls = []
        b.like_post = lambda n: (calls.append(n), (True, "liked"))[1]
        app.action_show_post(1); await pilot.pause()
        card = app.screen; assert isinstance(card, PostCard)
        for _ in range(3):
            await pilot.press("l"); await pilot.pause(0.5)
            assert card.heart_frames_shown == list(PostCard.HEART_FRAMES)  # grew then shrank
            assert not card.query_one("#heart").has_class("on")  # and went away
        assert calls == [1] and opened == []  # API like sent once, browser never
        assert b.state.liked == ["5"]
        if b.state.path:
            assert BotState(b.state.path).liked == ["5"]
        b.stopped = True


def test_liked_persists(tmp_path):
    s = BotState(tmp_path / "state.json"); s.liked.append("9"); s.save()
    assert BotState(tmp_path / "state.json").liked == ["9"]


def test_heart_frames_grow_then_shrink():
    sizes = [len(f) for f in PostCard.HEART_FRAMES]
    top = sizes.index(max(sizes))
    assert 0 < top < len(sizes) - 1 and sizes[:top + 1] == sorted(sizes[:top + 1]) and sizes[top:] == sorted(sizes[top:], reverse=True)
