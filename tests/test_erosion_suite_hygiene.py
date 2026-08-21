"""Unit tests for the test-hygiene sensor (parametrize candidates, cross-file copies)."""

from __future__ import annotations

from pathlib import Path

from erosion.models import CrossFileDuplicate, ParametrizeGroup, SuiteHygieneFinding
from erosion.suite_hygiene import collect_tests, compute, normalized_signature


def _tests(*bodies: tuple[str, str]) -> str:
    """Render ``(name, one-line body)`` pairs as a test module."""
    return "".join(f"def {name}():\n    {body}\n\n" for name, body in bodies)


# --- normalized_signature ----------------------------------------------------


def test_signature_ignores_names_constants_and_docstrings() -> None:
    a = "def test_a():\n    '''doc'''\n    assert parse('x') == 1\n"
    b = "def test_b():\n    assert parse('yy') == 2\n"
    assert normalized_signature(a) == normalized_signature(b)


def test_signature_distinguishes_structure() -> None:
    a = "def test_a():\n    assert parse('x') == 1\n"
    b = "def test_b():\n    assert parse('x') != 1\n"
    assert normalized_signature(a) != normalized_signature(b)


def test_signature_distinguishes_constant_types() -> None:
    a = "def test_a():\n    assert f(1) == 1\n"
    b = "def test_b():\n    assert f('1') == 1\n"
    assert normalized_signature(a) != normalized_signature(b)


# --- compute: parametrize groups --------------------------------------------


def test_three_identical_tests_in_one_file_form_a_parametrize_group() -> None:
    src = _tests(
        ("test_one", "assert f('a') == 1"),
        ("test_two", "assert f('b') == 2"),
        ("test_three", "assert f('c') == 3"),
        ("test_other", "assert g() is None"),
    )
    finding = compute({"tests/test_x.py": src})
    assert finding.parametrize_groups == (
        ParametrizeGroup(
            path="tests/test_x.py", names=("test_one", "test_two", "test_three")
        ),
    )
    assert finding.parametrize_copies == 2
    assert finding.total_tests == 4
    assert finding.total_files == 1


def test_group_below_min_group_is_not_reported() -> None:
    src = _tests(("test_one", "assert f('a') == 1"), ("test_two", "assert f('b') == 2"))
    finding = compute({"tests/test_x.py": src}, min_group=3)
    assert finding.parametrize_groups == ()
    assert finding.is_empty


def test_async_tests_and_class_methods_participate() -> None:
    src = (
        "class TestThing:\n"
        "    async def test_a(self):\n        assert await f('a') == 1\n"
        "    async def test_b(self):\n        assert await f('b') == 2\n"
        "    async def test_c(self):\n        assert await f('c') == 3\n"
    )
    finding = compute({"tests/test_y.py": src})
    assert finding.parametrize_groups[0].names == ("test_a", "test_b", "test_c")


def test_groups_sorted_largest_first_then_path() -> None:
    big = _tests(*((f"test_{i}", f"assert f('{i}') == {i}") for i in range(4)))
    small = _tests(*((f"test_{i}", f"assert g('{i}') == {i}") for i in range(3)))
    finding = compute({"tests/test_b.py": small, "tests/test_a.py": big})
    assert [g.path for g in finding.parametrize_groups] == [
        "tests/test_a.py",
        "tests/test_b.py",
    ]


# --- compute: cross-file duplicates -----------------------------------------


def test_same_name_and_body_in_two_files_is_a_cross_file_duplicate() -> None:
    body = _tests(("test_round_trip", "assert load(save(1)) == 1"))
    finding = compute({"tests/test_a.py": body, "tests/test_b.py": body})
    assert finding.cross_file_duplicates == (
        CrossFileDuplicate(
            name="test_round_trip", paths=("tests/test_a.py", "tests/test_b.py")
        ),
    )


def test_same_name_different_body_is_not_a_duplicate() -> None:
    a = _tests(("test_x", "assert f() == 1"))
    b = _tests(("test_x", "assert f() is None"))
    finding = compute({"tests/test_a.py": a, "tests/test_b.py": b})
    assert finding.cross_file_duplicates == ()


def test_unparseable_file_is_skipped_not_raised() -> None:
    finding = compute(
        {
            "tests/test_bad.py": "def test_(:\n",
            "tests/test_ok.py": _tests(("test_a", "pass")),
        }
    )
    assert isinstance(finding, SuiteHygieneFinding)
    assert finding.total_files == 2
    assert finding.total_tests == 1


# --- collect_tests -----------------------------------------------------------


def test_collect_tests_matches_pytest_globs_recursively(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    (tests / "regressions").mkdir(parents=True)
    (tests / "test_a.py").write_text("def test_a(): pass\n")
    (tests / "regressions" / "regression_issue_1.py").write_text("def test_r(): pass\n")
    (tests / "helpers.py").write_text("X = 1\n")
    (tests / "__pycache__").mkdir()
    (tests / "__pycache__" / "test_cached.py").write_text("def test_c(): pass\n")

    collected = collect_tests(tests)

    assert sorted(collected) == [
        "tests/regressions/regression_issue_1.py",
        "tests/test_a.py",
    ]
