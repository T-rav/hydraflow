"""Regression for #11004: the parallel regression lane must stay `--forked`.

#11004 is an xdist worker-state contamination flake — a test leaks a global
holding another test's tmp path, and every later test on that worker
FileExistsError-cascades (~24 innocents fail on a later RC run). `--reruns`
cannot fix it: a rerun stays on the already-poisoned worker. The fix is
per-test process isolation (`--forked`) on the parallel regression lane, so a
leak in one test cannot reach the next.

This guard fails if the fix is silently dropped — from the CI command or from
the declared dependency set. Static text checks (no subprocess), mirroring the
reap-serial-list drift guard (#10904).
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_YML = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"


def test_pytest_forked_is_a_declared_dependency() -> None:
    text = _PYPROJECT.read_text(encoding="utf-8")
    assert "pytest-forked" in text, (
        "pytest-forked must stay a declared dependency — it provides the "
        "--forked per-test isolation that kills the #11004 contamination flake"
    )


def test_parallel_regression_lane_uses_forked_isolation() -> None:
    text = _CI_YML.read_text(encoding="utf-8")
    # The parallel regression run: `pytest tests/regressions/ ... -n auto ...`.
    forked_parallel_lines = [
        line
        for line in text.splitlines()
        if "pytest tests/regressions/" in line and "-n auto" in line
    ]
    assert forked_parallel_lines, (
        "could not find the parallel regression lane (pytest tests/regressions/ "
        "-n auto ...) in ci.yml — did the job move?"
    )
    for line in forked_parallel_lines:
        assert "--forked" in line, (
            "the parallel regression lane must run with --forked (#11004): "
            f"{line.strip()!r}"
        )
