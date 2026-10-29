from xbot.app import XBotApp


async def test_ctrl_left_right_jump_words_and_shift_selects(mk):
    b = mk()
    app = XBotApp(bot=b, autostart=False)
    async with app.run_test(size=(120, 40)) as pilot:
        inp = app.query_one("#cmd"); inp.focus(); await pilot.pause()
        inp.value = "/post hello world"; inp.cursor_position = len(inp.value)
        await pilot.press("ctrl+left"); await pilot.pause()
        assert inp.cursor_position == len("/post hello ")
        await pilot.press("ctrl+left"); await pilot.pause()
        assert inp.cursor_position == len("/post ")
        await pilot.press("ctrl+right"); await pilot.pause()
        assert inp.cursor_position in (len("/post hello"), len("/post hello "))
        inp.cursor_position = len(inp.value)
        await pilot.press("shift+left", "shift+left"); await pilot.pause()
        assert inp.selected_text == "ld"
        inp.cursor_position = len(inp.value)
        await pilot.press("shift+home"); await pilot.pause()
        assert inp.selected_text == inp.value
        inp.cursor_position = 0
        await pilot.press("shift+end"); await pilot.pause()
        assert inp.selected_text == inp.value
