"""Unit tests for scripts/check_regression_rot_working_tree.py (#9597 Surface 2).

Pre-push advisory for uncommitted tests/regressions/ contract files — offline
(only ``git status --porcelain`` parsing), never blocks the push. Imported by
file path (mirrors tests/test_check_conflict_markers.py) since scripts/ isn't
on PYTHONPATH.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = (
    Path(__file__).parent.parent / "scripts" / "check_regression_rot_working_tree.py"
)
_spec = importlib.util.spec_from_file_location(
    "check_regression_rot_working_tree", _SCRIPT
)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
sys.modules["check_regression_rot_working_tree"] = guard
_spec.loader.exec_module(guard)


class TestFindUncommittedRegressionPaths:
    def test_untracked_file_is_found(self) -> None:
        porcelain = "?? tests/regressions/test_issue_1234.py\n"
        assert guard.find_uncommitted_regression_paths(porcelain) == [
            "tests/regressions/test_issue_1234.py"
        ]

    def test_modified_tracked_file_is_found(self) -> None:
        porcelain = " M tests/regressions/test_issue_5678.py\n"
        assert guard.find_uncommitted_regression_paths(porcelain) == [
            "tests/regressions/test_issue_5678.py"
        ]

    def test_renamed_file_reports_destination(self) -> None:
        porcelain = (
            "R  tests/regressions/old_name.py -> tests/regressions/test_issue_42.py\n"
        )
        assert guard.find_uncommitted_regression_paths(porcelain) == [
            "tests/regressions/test_issue_42.py"
        ]

    def test_clean_tree_returns_empty(self) -> None:
        assert guard.find_uncommitted_regression_paths("") == []

    def test_paths_outside_regressions_dir_excluded(self) -> None:
        porcelain = "?? src/some_module.py\n?? tests/test_other.py\n"
        assert guard.find_uncommitted_regression_paths(porcelain) == []

    def test_non_python_file_excluded(self) -> None:
        porcelain = "?? tests/regressions/notes.txt\n"
        assert guard.find_uncommitted_regression_paths(porcelain) == []

    def test_short_lines_are_skipped_without_raising(self) -> None:
        # A malformed/truncated porcelain line must not raise IndexError.
        assert guard.find_uncommitted_regression_paths("??\n") == []


class TestBuildWarning:
    def test_no_paths_yields_no_warning(self) -> None:
        assert guard.build_warning([]) is None

    def test_descriptive_filename_yields_no_warning(self) -> None:
        """A file with no parseable issue number is silently skipped —
        same precision rule as the committed-tree detector."""
        assert guard.build_warning(["tests/regressions/test_async_timeouts.py"]) is None

    def test_issue_numbered_file_is_named_in_the_warning(self) -> None:
        warning = guard.build_warning(["tests/regressions/test_issue_9836.py"])
        assert warning is not None
        assert "test_issue_9836.py" in warning
        assert "#9836" in warning

    def test_legacy_regression_prefix_is_recognized(self) -> None:
        warning = guard.build_warning(["tests/regressions/regression_issue_6709.py"])
        assert warning is not None
        assert "#6709" in warning

    def test_multiple_files_all_listed(self) -> None:
        warning = guard.build_warning(
            [
                "tests/regressions/test_issue_100.py",
                "tests/regressions/test_issue_200.py",
            ]
        )
        assert warning is not None
        assert "#100" in warning
        assert "#200" in warning


class TestMainNeverFails:
    def test_main_returns_zero_outside_a_git_repo(self, tmp_path, monkeypatch) -> None:
        """Even if `git status` fails entirely, main() must return 0 — advisory
        checks never block a push."""
        monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
        assert guard.main() == 0
