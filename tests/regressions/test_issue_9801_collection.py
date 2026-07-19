"""Regression: 72 regression_issue_*.py files were never collected (#9801/#9872).

pyproject's pytest config had no ``python_files`` override, so the default
``test_*.py`` glob silently skipped every ``regression_issue_NNNN.py`` file —
289 pinned-bug tests providing zero coverage since creation. This meta-guard
asserts every Python file in tests/regressions/ matches a configured
collection pattern, so a glob change can never silently orphan them again.
"""

from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_every_regression_file_matches_a_collection_pattern() -> None:
    config = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
    patterns = config["tool"]["pytest"]["ini_options"]["python_files"]

    orphans = [
        path.name
        for path in sorted((_REPO_ROOT / "tests" / "regressions").glob("*.py"))
        if path.name != "__init__.py"
        and not any(fnmatch.fnmatch(path.name, pat) for pat in patterns)
    ]

    assert orphans == [], (
        f"{len(orphans)} file(s) in tests/regressions/ match no pytest "
        f"python_files pattern and will silently never run: {orphans[:5]}"
    )


def test_legacy_regression_glob_is_configured() -> None:
    config = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
    patterns = config["tool"]["pytest"]["ini_options"]["python_files"]

    assert any(fnmatch.fnmatch("regression_issue_6408.py", pat) for pat in patterns)
