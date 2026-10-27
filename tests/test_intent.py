from xbot.app import ReplyEditor
class _E(ReplyEditor):
    text = "Hi & bye #ai"
def test_intent_url_encodes():
    e = _E.__new__(_E)
    e.post = {"id": "123"}
    assert e.intent_url() == "https://x.com/intent/post?in_reply_to=123&text=Hi%20%26%20bye%20%23ai"
