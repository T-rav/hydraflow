"""Regression tests ensuring legacy dead modules stay removed."""

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent


@pytest.mark.parametrize(
    ("relative_path", "why"),
    [
        pytest.param(
            "src/visual_diff.py",
            "superseded by visual_validator.py",
            id="visual_diff_source_file_is_removed",
        ),
        pytest.param(
            "tests/test_visual_diff.py",
            "the tests of a deleted module",
            id="visual_diff_test_file_is_removed",
        ),
        pytest.param(
            "src/scheduler.py",
            "multi-repo scheduler never integrated",
            id="scheduler_source_file_is_removed",
        ),
        pytest.param(
            "src/pre_issue_tracker.py",
            "local prep issue tracker never integrated",
            id="pre_issue_tracker_source_file_is_removed",
        ),
    ],
)
def test_removed_module_is_not_reintroduced(relative_path: str, why: str) -> None:
    """Guard against re-introduction of a module that was deliberately deleted."""
    assert not (_REPO_ROOT / relative_path).exists(), (
        f"{relative_path} was re-introduced; delete it ({why})."
    )
