import json, pytest
from xbot.commands import parse, CommandError
from xbot.queue import DraftQueue
from xbot.llm import FakeLLM, LLMFatal, LLMError
from xbot.config import load_env_file, redact


def test_queue_flow():
    q = DraftQueue()
    a, b = q.add("post", "x"), q.add("reply", "y", in_reply_to="5")
    q.edit(a.id, "x2"); q.approve(a.id); q.reject(b.id)
    assert a.text == "x2" and q.pending() == []
    with pytest.raises(ValueError): q.approve(a.id)
    with pytest.raises(KeyError): q.get(99)


@pytest.mark.parametrize("line,name,args,text", [
    ("/pause", "pause", [], ""), ("/align be witty", "align", [], "be witty"),
    ("/post hello world", "post", [], "hello world"), ("/reply 123 hi there", "reply", ["123"], "hi there"),
    ("/dryrun off", "dryrun", [False], ""), ("/edit 3 new", "edit", ["3"], "new"), ("/approve 2", "approve", ["2"], ""),
])
def test_parse_ok(line, name, args, text):
    c = parse(line); assert (c.name, c.args, c.text) == (name, args, text)


@pytest.mark.parametrize("line", ["hello", "/nope", "/post", "/reply abc hi", "/reply 1", "/dryrun maybe", "/approve x"])
def test_parse_bad(line):
    with pytest.raises(CommandError): parse(line)


def test_loop_drafts_replies_and_approve_sends(mk):
    b = mk(FakeLLM(["thanks!"]), [{"id": "10", "text": "@me hi", "author_id": "u1"}], post_every_n_ticks=0)
    assert b.tick() == 1
    d = b.queue.pending()[0]
    assert d.in_reply_to == "10" and b.since_id == "10"
    b.handle(parse(f"/approve @{d.id}"))
    assert b.dry_x.sent == [{"id": b.dry_x.sent[0]["id"], "text": "thanks!", "in_reply_to": "10"}]
    assert any("DRY-SEND" in f for f in b.feed)


def test_original_post_cadence(mk):
    b = mk(FakeLLM(), post_every_n_ticks=2, topics=["linux"])
    assert b.tick() == 0 and b.tick() == 1
    assert b.queue.pending()[0].kind == "post"


def test_nothing_sent_without_approval(mk):
    b = mk(FakeLLM(), [{"id": "1", "text": "yo"}], post_every_n_ticks=1)
    b.tick(); assert b.dry_x.sent == []


def test_fatal_llm_pauses_no_retry(mk):
    llm = FakeLLM(fail=LLMFatal("xAI credit exhausted"))
    b = mk(llm, [{"id": "1", "text": "a"}, {"id": "2", "text": "b"}])
    b.tick()
    assert b.paused and len(llm.calls) == 1 and b.tick() == 0
    assert any("PAUSED" in f for f in b.feed)


def test_transient_llm_error_logged(mk):
    b = mk(FakeLLM(fail=LLMError("proxy down")), [{"id": "1", "text": "a"}])
    b.tick(); assert not b.paused and any("proxy down" in f for f in b.feed)


def test_align_pause_manual_post_status(mk):
    b = mk()
    b.handle(parse("/align pirate voice")); assert "pirate voice" in b.system_prompt()
    b.handle(parse("/posttopics rust, vim")); assert b.cfg.topics == ["rust", "vim"]
    b.handle(parse("/pause")); assert b.tick() == 0
    b.handle(parse("/post manual one")); assert b.dry_x.sent == []
    d = b.queue.pending()[-1]; assert d.source == "manual"
    b.handle(parse(f"/approve @{d.id}")); assert b.dry_x.sent[-1]["text"] == "manual one"
    b.handle(parse("/status")); assert "PAUSED" in b.feed[-1]


def test_jsonl_log_and_redaction(mk, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "sk-supersecret")
    b = mk()
    b.log.event("error", "key sk-supersecret leaked?")
    lines = [json.loads(l) for l in b.log.path.read_text().splitlines()]
    assert "sk-supersecret" not in b.log.path.read_text() and lines[-1]["msg"].endswith("*** leaked?")


def test_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("XBOT_TEST_K", raising=False)
    p = tmp_path / "env"; p.write_text("# c\nXBOT_TEST_K='v1'\n"); p.chmod(0o644)
    w = load_env_file(tmp_path)
    import os; assert os.environ["XBOT_TEST_K"] == "v1" and w


def test_dryrun_off_uses_real_factory(mk):
    b = mk(); sent = []
    class R:
        def post(self, text, in_reply_to=None): sent.append(text); return "1"
    b.real_x_factory = R
    b.handle(parse("/dryrun off")); b.handle(parse("/post live"))
    b.handle(parse(f"/approve @{b.queue.pending()[-1].id}")); assert sent == ["live"]
