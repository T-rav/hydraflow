"""Regression for issue #10594.

``verify_cite_ast`` in ``wiki_rot_citations`` resolves a cited
``path.py:Symbol`` by AST-walking the module for defs and classes only
(``_collect_defined_symbols`` gathered ``FunctionDef`` /
``AsyncFunctionDef`` / ``ClassDef`` nodes). Module-level *constants* —
plain ``NAME = ...`` (``ast.Assign``) and annotated ``NAME: T = ...``
(``ast.AnnAssign``) targets — were never collected, so a cite to a live
module-level constant (e.g. ``src/agent.py:_SELF_CHECK_CHECKLIST`` or
``src/review_advisor.py:_SURFACE_DEFAULTS``) was reported broken every
tick and escalated after 3 attempts — a permanent false-positive class no
code change could ever clear.

The fix mirrors ``adr_citation_resolve`` (which already resolves bare
module-level names via ``ast.Assign`` / ``ast.AnnAssign`` targets): the
verifier must treat module-level assigned names as valid resolvable
symbols. A cited constant that exists on disk must resolve; a
genuinely-absent symbol must still report broken.
"""

from __future__ import annotations

from pathlib import Path

from wiki_rot_citations import verify_cite_ast


def _write_module(tmp_path: Path, body: str) -> None:
    mod = tmp_path / "src" / "foo.py"
    mod.parent.mkdir(parents=True, exist_ok=True)
    mod.write_text(body)


def test_verify_cite_ast_resolves_plain_module_constant(tmp_path: Path) -> None:
    # A live module-level ``NAME = ...`` constant must resolve.
    _write_module(tmp_path, "SOME_CONST = {'a': 1}\n\ndef helper(): ...\n")
    ok, symbols = verify_cite_ast(tmp_path, "src/foo.py", "SOME_CONST")
    assert ok
    assert "SOME_CONST" in symbols


def test_verify_cite_ast_resolves_annotated_module_constant(tmp_path: Path) -> None:
    # An annotated ``NAME: T = ...`` (``ast.AnnAssign``) target must resolve.
    _write_module(tmp_path, "TYPED_CONST: int = 5\n")
    ok, symbols = verify_cite_ast(tmp_path, "src/foo.py", "TYPED_CONST")
    assert ok
    assert "TYPED_CONST" in symbols


def test_verify_cite_ast_resolves_tuple_unpacked_constant(tmp_path: Path) -> None:
    # Tuple-unpacked module-level assignment targets must each resolve.
    _write_module(tmp_path, "LEFT, RIGHT = 1, 2\n")
    ok_left, _ = verify_cite_ast(tmp_path, "src/foo.py", "LEFT")
    ok_right, _ = verify_cite_ast(tmp_path, "src/foo.py", "RIGHT")
    assert ok_left
    assert ok_right


def test_verify_cite_ast_still_reports_absent_symbol_broken(tmp_path: Path) -> None:
    # A symbol that is genuinely not defined must still be reported broken.
    _write_module(tmp_path, "SOME_CONST = 1\n\ndef helper(): ...\n")
    ok, symbols = verify_cite_ast(tmp_path, "src/foo.py", "NOT_THERE")
    assert not ok
    assert "NOT_THERE" not in symbols


def test_verify_cite_ast_ignores_function_local_assignment(tmp_path: Path) -> None:
    # A name bound only inside a function body is NOT a module-level symbol
    # and must not spuriously resolve as a top-level constant cite.
    _write_module(
        tmp_path, "def helper():\n    local_only = 3\n    return local_only\n"
    )
    ok, symbols = verify_cite_ast(tmp_path, "src/foo.py", "local_only")
    assert not ok
    assert "local_only" not in symbols
