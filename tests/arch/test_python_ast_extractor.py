from __future__ import annotations

from pathlib import Path

from arch.python_ast import python_ast_extractor

FIXTURE = Path(__file__).parent / "fixtures" / "py_repo"


def test_extracts_module_edges() -> None:
    graph = python_ast_extractor(str(FIXTURE))
    assert graph.module_unit == "file"
    assert ("src/a.py", "src/b.py") in graph.edges
    assert ("src/a.py", "src/c.py") in graph.edges
    assert ("src/c.py", "src/b.py") in graph.edges


def test_skips_stdlib_and_unresolved_imports() -> None:
    graph = python_ast_extractor(str(FIXTURE))
    assert not any("os" in target for _, target in graph.edges)


def test_ignores_dotfiles_and_venv() -> None:
    graph = python_ast_extractor(str(FIXTURE))
    for _, target in graph.edges:
        assert not target.startswith(".")
        assert "venv" not in target
