import json
from xbot.configcli import cli
from xbot.config import Config


def run(tmp_path, *a, **k):
    out = []
    rc = cli(list(a), config_dir=tmp_path, out=out.append, **k)
    return rc, "\n".join(out)


def test_show_prints_path_and_settings(tmp_path):
    rc, o = run(tmp_path)
    assert rc == 0 and str(tmp_path / "config.json") in o and "llm_rpm = 5" in o


def test_set_llm_rpm_1_saves_and_clamps_auto(tmp_path):
    rc, o = run(tmp_path, "llm_auto_rpm", "1"); assert rc == 0
    rc, o = run(tmp_path, "llm_rpm", "1"); assert rc == 0
    assert json.loads((tmp_path / "config.json").read_text())["llm_rpm"] == 1
    run(tmp_path, "llm_auto_rpm", "5")
    c = Config.load(tmp_path); assert c.llm_rpm == 1 and c.llm_auto_rpm == 1


def test_bad_type_range_and_unknown_key(tmp_path):
    assert run(tmp_path, "llm_rpm", "fast")[0] == 2
    rc, o = run(tmp_path, "llm_rpm", "-1"); assert rc == 2 and ">= 1" in o
    rc, o = run(tmp_path, "nope", "1"); assert rc == 2 and "Valid keys" in o and "llm_rpm" in o
    assert not (tmp_path / "config.json").exists()


def test_bool_and_edit(tmp_path, monkeypatch):
    assert run(tmp_path, "dry_run", "false")[0] == 0 and Config.load(tmp_path).dry_run is False
    calls = []
    monkeypatch.setenv("EDITOR", "vim -n")
    assert run(tmp_path, "edit", run=lambda c: calls.append(c) or 0)[0] == 0
    assert calls == [["vim", "-n", str(tmp_path / "config.json")]]
    monkeypatch.delenv("EDITOR")
    run(tmp_path, "edit", run=lambda c: calls.append(c) or 0); assert calls[-1][0] == "nano"


def test_never_prints_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-SECRETVALUE123")
    (tmp_path / "config.json").write_text(json.dumps({"persona": "hi xai-SECRETVALUE123"}))
    _, o = run(tmp_path)
    assert "SECRETVALUE" not in o


def test_bad_json_loads_defaults_with_one_line(tmp_path):
    (tmp_path / "config.json").write_text('{\n "search_query":\n "search_max_results": 10\n}')
    c = Config.load(tmp_path)
    assert c.load_error and "\n" not in c.load_error and "line 3 col" in c.load_error and "xbot config edit" in c.load_error
    assert c.search_query == Config().search_query
    rc, o = run(tmp_path); assert rc == 0 and "config error" in o


def test_empty_or_bad_values_fall_back(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"search_query": "  ", "llm_rpm": -2, "max_pending": "x", "dry_run": False}))
    c = Config.load(tmp_path)
    assert c.search_query == Config().search_query and c.llm_rpm == 5 and c.max_pending == Config().max_pending
    assert c.dry_run is False and len(c.load_warnings) == 3


def test_save_keeps_broken_file_and_writes_valid_json(tmp_path):
    (tmp_path / "config.json").write_text("{bad")
    assert run(tmp_path, "llm_rpm", "3")[0] == 0
    assert (tmp_path / "config.json.bad").read_text() == "{bad"
    assert json.loads((tmp_path / "config.json").read_text())["llm_rpm"] == 3


def test_edit_warns_and_reopens_until_valid(tmp_path):
    p = tmp_path / "config.json"; p.write_text("{}")
    seq = ["{oops", '{"llm_rpm": 2}']
    def editor(cmd): p.write_text(seq.pop(0)); return 0
    rc, o = run(tmp_path, "edit", run=editor, ask=lambda q: "y")
    assert rc == 0 and "by hand can break xbot" in o and "config error" in o and "config OK" in o
    p.write_text("{oops"); rc, _ = run(tmp_path, "edit", run=lambda c: 0, ask=lambda q: "n"); assert rc == 2


def test_config_cli_writes_valid_json(tmp_path):
    run(tmp_path, "search_query", '"quoted" @usedotai, x')
    assert json.loads((tmp_path / "config.json").read_text())["search_query"] == '"quoted" @usedotai, x'


def test_main_crash_prints_one_line(tmp_path, monkeypatch, capsys):
    import pytest, xbot.app as A, xbot.config as C
    monkeypatch.setattr(C, "STATE_DIR", tmp_path)
    class Boom:
        def __init__(self): self._cli_mode = False
        def run(self): raise RuntimeError("kaput")
        def shutdown(self): pass
    monkeypatch.setattr(A, "XBotApp", Boom)
    with pytest.raises(SystemExit):
        A.main([])
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "kaput" in err and "Traceback" not in err
    assert "Traceback" in (tmp_path / "crash.log").read_text()


def test_reset_backs_up_and_writes_defaults(tmp_path):
    (tmp_path / "config.json").write_text("{broken")
    rc, o = run(tmp_path, "reset")
    baks = list(tmp_path.glob("config.json.bak.*"))
    assert rc == 0 and len(baks) == 1 and baks[0].read_text() == "{broken" and str(baks[0]) in o and o.count("\n") == 0
    assert Config.load(tmp_path).load_error is None and json.loads((tmp_path / "config.json").read_text())["llm_rpm"] == 5
    (tmp_path / "config.json").write_text("{x"); assert "xbot config reset" in Config.load(tmp_path).load_error
