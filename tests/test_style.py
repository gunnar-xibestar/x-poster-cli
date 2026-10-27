from xbot.commands import parse
from xbot.llm import FakeLLM
from xbot.style import StyleStore, examples_block, KEEP
from tests.test_search import P, S


class Spy(FakeLLM):
    def __init__(self):
        super().__init__(["grok reply"]); self.systems = []
    def complete(self, system, user):
        self.systems.append(system); return "grok reply"


def test_edit_then_approve_records_and_prompt_uses_it(mk):
    llm = Spy()
    b = mk(llm, search=[P(1, text="rust 2.0 is out")], **S(max_pending=4)); b.tick()
    d = b.queue.pending()[0]
    b.handle(parse(f"/edit @{d.id} congrats, the borrow checker finally likes me"))
    b.handle(parse(f"/approve @{d.id}"))
    recs = b.style.load()
    assert recs[-1]["final"].startswith("congrats") and recs[-1]["draft"] == "grok reply"
    assert "replies in the user's voice" in b.system_prompt() and "borrow checker" in b.system_prompt()


def test_unedited_approve_not_recorded(mk):
    b = mk(FakeLLM(["same"]), search=[P(1)], **S()); b.tick()
    b.handle(parse(f"/approve @{b.queue.pending()[0].id}")); assert b.style.load() == []


def test_zero_disables_and_clear(mk):
    b = mk(FakeLLM(), search=[P(1)], **S()); b.tick()
    b.style.add("1", "post", "draft", "mine")
    b.cfg.style_examples = 0; assert "voice" not in b.system_prompt()
    b.cfg.style_examples = 8; assert "voice" in b.system_prompt()
    b.handle(parse("/style clear")); assert b.style.load() == [] and "voice" not in b.system_prompt()


def test_hidden_or_filtered_never_used(mk):
    b = mk(FakeLLM(), search=[P(1, text="secret thing"), P(2)], **S()); b.tick()
    b.style.add("1", "secret thing", "d", "mine 1")
    b.hide_post(1)
    assert "secret thing" not in b.system_prompt()
    assert not b.learn_style("1", "secret thing", "d", "other")


def test_keep_last_50_and_truncate(tmp_path):
    s = StyleStore(tmp_path / "s.jsonl")
    for i in range(60):
        s.add(str(i), "x" * 1000, "d", f"final {i}")
    r = s.load(); assert len(r) == KEEP and r[0]["final"] == "final 10" and len(r[0]["post"]) <= 240
    blk = examples_block(r, 3); assert blk.count("User's reply") == 3 and "final 59" in blk


def test_editor_save_records(mk):
    b = mk(FakeLLM(), search=[P(5, text="hello")], **S()); b.tick()
    b.queue_reply_to_found(1, "my words", grok_text="grok words")
    assert b.style.load()[-1]["final"] == "my words"
