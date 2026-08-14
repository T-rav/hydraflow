"""Regression pin for #11138 — `HEAD:`-prefixed paths in escape evidence.

`regression_hits` returned `git grep -l ... HEAD` output verbatim, so the
permanent ledger resolution notes (and HITL close comments) recorded
`HEAD:tests/regressions/...` — a string no reader can open. The rev prefix
is stripped at the adapter boundary.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from escape.auto_diagnose import regression_hits


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_regression_hits_paths_have_no_rev_prefix(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "tests" / "regressions").mkdir(parents=True)
    (repo / "tests" / "regressions" / "test_bug_777.py").write_text(
        "# Regression for #777\n"
    )
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@e.dev")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")

    hits = regression_hits(repo, issue_ref=777, shas=())
    assert hits == ("tests/regressions/test_bug_777.py",)
