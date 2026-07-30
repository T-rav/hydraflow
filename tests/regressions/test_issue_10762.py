"""Regression for issue #10762.

``extract_cites`` in ``wiki_rot_citations`` had three cite styles — Style-A
(``path/to/module.py:symbol``), Style-B (dotted ``src.module.Class``) and
Style-C (bare names inside ```` ```python ```` fences). A bare backticked
identifier in ordinary prose — e.g. "Run ``wiki_lesson_coverage`` to tier
predecessors" — matched none of them, so ``extract_cites`` returned nothing
and ``WikiRotDetectorLoop`` never filed rot for a dead-end tool reference.
That is exactly how issue #10754's phantom-tool guidance survived in live
entries.

The fix adds Style-D: a bare backticked snake_case token in *imperative*
position (``run`` / ``invoke`` / ``execute`` + the backtick) is extracted as
a ``style="bare"`` cite and resolved by presence against a symbol corpus
(module/script basenames + defined symbols) rather than AST verification.
"""

from __future__ import annotations

from pathlib import Path

from wiki_rot_citations import (
    build_symbol_corpus,
    extract_cites,
    resolve_bare_cite,
)


def _bare(text: str) -> set[str]:
    return {c.symbol for c in extract_cites(text) if c.style == "bare"}


def test_style_d_extracts_imperative_bare_tool_cite() -> None:
    text = "Run `wiki_lesson_coverage` to tier left_on_primary predecessors."
    cites = [c for c in extract_cites(text) if c.style == "bare"]
    assert len(cites) == 1
    assert cites[0].symbol == "wiki_lesson_coverage"
    assert cites[0].module == ""  # bare cite carries no module/symbol pair


def test_style_d_accepts_invoke_and_execute_verbs() -> None:
    assert _bare("invoke `topic_repair_tool` before merging") == {"topic_repair_tool"}
    assert _bare("execute the `phantom_auditor` script") == {"phantom_auditor"}


def test_style_d_strips_script_suffix_to_basename() -> None:
    # ``foo.py`` resolves as the module stem ``foo`` for corpus lookup.
    cites = [c for c in extract_cites("Run `dead_script.py` now.") if c.style == "bare"]
    assert cites and cites[0].symbol == "dead_script"


def test_style_d_ignores_non_imperative_backticked_prose() -> None:
    # A backticked identifier NOT governed by an imperative verb is prose,
    # not a runnable-tool cite — must not be extracted as a bare cite.
    text = "The `cancel_fn` and `resume_fn` callbacks decouple the loop."
    assert _bare(text) == set()


def test_style_d_ignores_metavariable_placeholders() -> None:
    # Documentation grammar examples must never self-report.
    assert _bare("Run `my_module` as an example.") == set()
    assert _bare("invoke `snake_case` to see the shape") == set()
    # gotchas/1186 documents Style-D with the literal example
    # "Run `some_missing_tool`" — the entry that describes the rule must not
    # trip it (the self-referential false-positive class, #10754).
    assert _bare("Run `some_missing_tool`") == set()


def test_build_symbol_corpus_includes_stems_and_symbols(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "real_module.py").write_text(
        "def real_function():\n    return 1\n\nclass RealClass:\n    pass\n"
    )
    (tmp_path / "scripts" / "real_tool.py").write_text("print('hi')\n")
    corpus = build_symbol_corpus(tmp_path)
    assert "real_module" in corpus  # file stem
    assert "real_tool" in corpus  # script stem
    assert "real_function" in corpus  # defined symbol
    assert "RealClass" in corpus


def test_build_symbol_corpus_tolerates_broken_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "broken.py").write_text("def (:\n")  # syntax error
    (tmp_path / "src" / "ok.py").write_text("def survives():\n    return 1\n")
    corpus = build_symbol_corpus(tmp_path)  # must not raise
    assert "broken" in corpus  # stem still added
    assert "survives" in corpus


def test_resolve_bare_cite_presence_and_absence() -> None:
    corpus = frozenset({"real_tool", "real_function"})
    assert resolve_bare_cite("real_tool", corpus) is True
    assert resolve_bare_cite("real_tool.py", corpus) is True  # suffix stripped
    assert resolve_bare_cite("wiki_lesson_coverage", corpus) is False
