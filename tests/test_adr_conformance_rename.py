"""Unit tests for adr_conformance.find_renamed_pytest_node (bead advisor-fqk2).

Pure function: given an UNRESOLVED pytest node target, look for a
high-confidence rename among tests/**/*.py. High-confidence == exactly one
other file defines the same bare name; zero or multiple matches must return
None so the caller (AdrConformanceLoop._detect_rename) routes to FILE_ISSUE
rather than a possibly-wrong REPOINT.
"""

from __future__ import annotations

from pathlib import Path

from adr_conformance import find_renamed_pytest_node


def test_unambiguous_function_rename_found(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "new_home.py").write_text("def test_x():\n    assert True\n")
    result = find_renamed_pytest_node("tests/old.py::test_x", tmp_path)
    assert result == "pytest:tests/new_home.py::test_x"


def test_ambiguous_rename_returns_none(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "a.py").write_text("def test_x():\n    assert True\n")
    (tmp_path / "tests" / "b.py").write_text("def test_x():\n    assert True\n")
    assert find_renamed_pytest_node("tests/old.py::test_x", tmp_path) is None


def test_no_match_returns_none(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "a.py").write_text("def test_y():\n    assert True\n")
    assert find_renamed_pytest_node("tests/old.py::test_x", tmp_path) is None


def test_class_method_rename_preserved(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "new_home.py").write_text(
        "class TestFoo:\n    def test_bar(self):\n        assert True\n"
    )
    result = find_renamed_pytest_node("tests/old.py::TestFoo::test_bar", tmp_path)
    assert result == "pytest:tests/new_home.py::TestFoo::test_bar"


def test_class_method_ambiguous_when_multiple_files_define_it(
    tmp_path: Path,
) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "a.py").write_text(
        "class TestFoo:\n    def test_bar(self):\n        assert True\n"
    )
    (tmp_path / "tests" / "b.py").write_text(
        "class TestFoo:\n    def test_bar(self):\n        assert True\n"
    )
    assert find_renamed_pytest_node("tests/old.py::TestFoo::test_bar", tmp_path) is None


def test_class_method_not_matched_when_method_in_different_class(
    tmp_path: Path,
) -> None:
    # Same bare method name in an unrelated class must not count as a match
    # (mirrors the _pytest_node_defined false-positive guard).
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "other.py").write_text(
        "class TestBaz:\n    def test_bar(self):\n        assert True\n"
    )
    assert find_renamed_pytest_node("tests/old.py::TestFoo::test_bar", tmp_path) is None


def test_make_target_out_of_scope_returns_none(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("new-target:\n\techo hi\n")
    # This function only understands pytest-shaped node targets; passing a
    # bare make target (no "::") degenerates to a module-only citation with
    # no name part, which is explicitly out of scope -> None.
    assert find_renamed_pytest_node("old-target", tmp_path) is None


def test_param_suffix_stripped_when_matching(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "new_home.py").write_text("def test_x():\n    assert True\n")
    result = find_renamed_pytest_node("tests/old.py::test_x[case1]", tmp_path)
    assert result == "pytest:tests/new_home.py::test_x"


def test_module_only_citation_returns_none(tmp_path: Path) -> None:
    # No "::name" part at all -> nothing to search for by name.
    (tmp_path / "tests").mkdir()
    assert find_renamed_pytest_node("tests/old.py", tmp_path) is None


def test_deep_nesting_unsupported_returns_none(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    assert (
        find_renamed_pytest_node("tests/old.py::TestFoo::Nested::test_bar", tmp_path)
        is None
    )


def test_missing_tests_dir_returns_none(tmp_path: Path) -> None:
    assert find_renamed_pytest_node("tests/old.py::test_x", tmp_path) is None


def test_original_file_excluded_even_if_it_still_exists(tmp_path: Path) -> None:
    # If the "old" file still exists (e.g. same name, different content) it
    # must not count as a candidate match against itself; only genuinely
    # different files matter for a rename.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "old.py").write_text("def test_x():\n    assert True\n")
    # Only the original defines it -> zero *other* matches -> None.
    assert find_renamed_pytest_node("tests/old.py::test_x", tmp_path) is None


def test_unreadable_file_does_not_raise(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    bad = tmp_path / "tests" / "bad.py"
    bad.write_text("def test_x(\n    this is not valid python\n")
    good = tmp_path / "tests" / "good.py"
    good.write_text("def test_x():\n    assert True\n")
    # bad.py has a syntax error and must be silently skipped, not raise.
    result = find_renamed_pytest_node("tests/old.py::test_x", tmp_path)
    assert result == "pytest:tests/good.py::test_x"
