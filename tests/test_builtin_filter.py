from xbot.config import Config
from tests.test_search import P, S


def test_builtin_words_hidden_but_not_listed(mk):
    b = mk(xonly=True, search=[P(1, text="sissy content here"), P(2, text="Feminization stuff"), P(3, text="rust tips")], **S())
    b.tick()
    assert [p["id"] for _, p in b.visible_found()] == ["3"]
    assert not {"domme", "feminization", "sissy"} & set(Config().filter_words)
    b.cfg.filter_words = ["foo"]; b.cfg.auto_filter = False  # user edits / disables filters: still hidden
    assert [p["id"] for _, p in b.visible_found()] == ["3"]


def test_builtin_words_not_in_docs():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    text = (root / "README.md").read_text() + "".join(p.read_text() for p in (root / "docs").glob("*.md"))
    assert not any(w in text.lower() for w in ("domme", "feminization", "sissy"))
