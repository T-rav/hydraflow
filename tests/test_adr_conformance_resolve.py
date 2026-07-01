from pathlib import Path

from adr_conformance import MUTATING_MAKE_TARGETS, is_mutating, resolve_check
from adr_index import Check


def test_pytest_check_resolves_by_ast(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text("def test_alpha():\n    assert True\n")
    assert resolve_check(Check("pytest", "tests/t.py::test_alpha", "pytest:tests/t.py::test_alpha"), tmp_path)
    assert not resolve_check(Check("pytest", "tests/t.py::test_missing", "x"), tmp_path)


def test_pytest_parametrized_matches_base_name(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text("def test_p():\n    assert True\n")
    assert resolve_check(Check("pytest", "tests/t.py::test_p[case1]", "x"), tmp_path)


def test_make_check_resolves_by_makefile_grep(tmp_path):
    (tmp_path / "Makefile").write_text("arch-check:\n\techo hi\n")
    assert resolve_check(Check("make", "arch-check", "make:arch-check"), tmp_path)
    assert not resolve_check(Check("make", "nope", "make:nope"), tmp_path)


def test_prose_never_resolves(tmp_path):
    assert not resolve_check(Check("prose", "human review", "human review"), tmp_path)


def test_mutating_targets_flagged():
    assert is_mutating(Check("make", "lint-ul", "make:lint-ul"))
    assert is_mutating(Check("make", "arch-regen", "make:arch-regen"))
    assert not is_mutating(Check("make", "arch-check", "make:arch-check"))
    assert not is_mutating(Check("pytest", "tests/t.py::t", "x"))
    assert "lint-ul" in MUTATING_MAKE_TARGETS
