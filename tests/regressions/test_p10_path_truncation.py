"""Regression: P10.3 `_touched_regressions` must not be fooled by `git`'s
`--stat` path truncation.

`git show --stat` abbreviates long paths with `...`, so a commit that added a
real regression test under a long path (e.g.
`tests/regressions/test_issue_9419_9421_adr_drift.py`) had its
`tests/regressions/` prefix truncated away and was false-flagged as missing a
test. The fix switches to `git show --name-only` (full, untruncated paths).
This reproduces the truncation case and pins the corrected behaviour.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.hydraflow_audit.checks.p10_tdd import _touched_regressions

# Long enough that `git show --stat` truncates the leading path segments.
_LONG_REGRESSION_PATH = (
    "tests/regressions/"
    "test_a_deliberately_long_regression_filename_that_git_stat_truncates.py"
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _commit_long_regression_file(tmp_path: Path) -> str:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    target = tmp_path / _LONG_REGRESSION_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_x() -> None:\n    assert True\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "fix(thing): repair the thing")
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_touched_regressions_sees_long_path_regression_test(tmp_path: Path) -> None:
    sha = _commit_long_regression_file(tmp_path)

    assert _touched_regressions(tmp_path, sha) is True


def test_stat_output_would_have_truncated_the_prefix(tmp_path: Path) -> None:
    sha = _commit_long_regression_file(tmp_path)

    stat = subprocess.run(
        ["git", "show", "--stat", "--format=", sha],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    ).stdout

    assert "tests/regressions/" not in stat
