"""Regression: P10.3 must not count `fix(...)` commits that touch only tests.

During the ADR-0100 conformance work, #9697 made the audit's P10.3
(regression-test discipline) check real for the first time. The remediation
that followed produced several `fix(...)` commits that touched only test
files — a scenario-test update (#9700) and the regression test for the
timestamp bug (#9699). The per-commit heuristic counted each as a bug fix
lacking its own regression test, dragging compliance below the 60% threshold
and reddening staging's Principles Audit repeatedly.

A commit that touches only files under ``tests/`` is test maintenance, not a
product bug fix. This test pins that exclusion at the check level, using the
same temp-git-repo harness as ``tests/test_hydraflow_audit_p10_checks.py``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from scripts.hydraflow_audit import registry  # noqa: F401
from scripts.hydraflow_audit.checks import p10_tdd  # noqa: F401
from scripts.hydraflow_audit.models import CheckContext, Status


def _git_env() -> dict[str, str]:
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }


def _commit(tmp: Path, subject: str, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp, check=True, env=_git_env())
    subprocess.run(
        ["git", "commit", "-q", "-m", subject], cwd=tmp, check=True, env=_git_env()
    )


def _rev(tmp: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_p103_excludes_a_test_only_fix_commit(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    _commit(tmp_path, "feat: seed", {"README.md": "x\n"})
    # A fix() commit touching only tests/ — pre-exclusion this warned (1/1
    # uncovered); it must now be excluded from the ratio entirely.
    _commit(
        tmp_path,
        "fix(x): update a scenario test for new behaviour",
        {"tests/scenarios/test_x.py": "def test_x(): pass\n"},
    )
    check = registry.get("P10.3")
    assert check is not None
    finding = check(CheckContext(root=tmp_path))
    assert finding.status is Status.PASS
    assert "no fix/bug commits" in (finding.message or "")


def test_is_test_only_commit_distinguishes_product_from_test(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    _commit(tmp_path, "feat: seed", {"README.md": "x\n"})
    _commit(tmp_path, "test: only", {"tests/test_a.py": "def test_a(): pass\n"})
    test_only_sha = _rev(tmp_path)
    _commit(tmp_path, "fix: product", {"src/a.py": "def f(): return 1\n"})
    product_sha = _rev(tmp_path)

    assert p10_tdd._is_test_only_commit(tmp_path, test_only_sha) is True
    assert p10_tdd._is_test_only_commit(tmp_path, product_sha) is False
