"""Unit tests for the test-hygiene baseline (high-water marks + exceeded check)."""

from __future__ import annotations

from pathlib import Path

from erosion.models import ParametrizeGroup, SuiteHygieneFinding
from erosion.suite_hygiene_baseline import (
    SuiteHygieneBaseline,
    exceeded,
    load_suite_hygiene_baseline,
    save_suite_hygiene_baseline,
)


def _finding(copies: int = 0, dups: int = 0) -> SuiteHygieneFinding:
    from erosion.models import CrossFileDuplicate

    groups = tuple(
        ParametrizeGroup(path=f"tests/test_{i}.py", names=("test_a", "test_b"))
        for i in range(copies)
    )
    cross = tuple(
        CrossFileDuplicate(
            name=f"test_{i}", paths=("tests/test_a.py", "tests/test_b.py")
        )
        for i in range(dups)
    )
    return SuiteHygieneFinding(
        total_files=3,
        total_tests=30,
        parametrize_groups=groups,
        cross_file_duplicates=cross,
    )


def test_missing_baseline_is_empty_and_never_exceeded(tmp_path: Path) -> None:
    baseline = load_suite_hygiene_baseline(tmp_path / "nope.yaml")
    assert baseline == SuiteHygieneBaseline()
    # No recorded mark means nothing to ratchet against yet.
    assert exceeded(_finding(copies=5, dups=2), baseline) == ()


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "th.yaml"
    save_suite_hygiene_baseline(path, _finding(copies=4, dups=1), comment="initial")

    loaded = load_suite_hygiene_baseline(path)

    assert loaded.comment == "initial"
    assert loaded.parametrize_copies == 4
    assert loaded.cross_file_duplicates == 1
    assert loaded.total_tests == 30


def test_exceeded_names_each_metric_above_its_mark() -> None:
    baseline = SuiteHygieneBaseline(
        parametrize_copies=4, cross_file_duplicates=1, total_tests=30
    )
    messages = exceeded(_finding(copies=6, dups=3), baseline)
    assert len(messages) == 2
    assert "parametrize copies 6 > baseline 4" in messages[0]
    assert "cross-file duplicates 3 > baseline 1" in messages[1]


def test_at_or_below_mark_is_not_exceeded() -> None:
    baseline = SuiteHygieneBaseline(
        parametrize_copies=4, cross_file_duplicates=1, total_tests=30
    )
    assert exceeded(_finding(copies=4, dups=0), baseline) == ()
