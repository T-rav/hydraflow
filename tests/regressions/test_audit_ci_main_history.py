"""Regression: the Principles Audit CI job must see main-branch history.

Bead advisor-vm0r: the ``audit`` job ran on the actions/checkout default
(depth-1) and fetched ``origin/main`` with ``--depth=1``. P5.6
(``git log ... main``: no local ``main`` ref existed, and bare ``main``
never resolves to ``refs/remotes/origin/main``) and P10.3
(``git log <baseline>..HEAD``: the baseline SHA was outside the shallow
clone) both failed and silently degraded to NA, so two git-history
principles were unenforced in CI.

These tests pin the workflow shape and baseline format that keep the two
checks live:

1. the audit job's checkout uses ``fetch-depth: 0``;
2. the explicit main fetch is not shallow (no ``--depth``);
3. ``.hydraflow-audit-baseline`` holds a date/timestamp baseline that
   P10.3 turns into a branch-independent ``--since`` selector (a SHA
   baseline would have to be an ancestor of both staging and main, which
   RC-promotion squashing makes impossible to keep fresh).
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _audit_job_steps() -> list[dict]:
    ci = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    return ci["jobs"]["audit"]["steps"]


def test_audit_job_checkout_fetches_full_history() -> None:
    checkout = next(
        step
        for step in _audit_job_steps()
        if "actions/checkout" in str(step.get("uses", ""))
    )
    assert checkout.get("with", {}).get("fetch-depth") == 0, (
        "audit job checkout must use fetch-depth: 0 — a shallow checkout "
        "makes P5.6/P10.3 silently degrade to NA"
    )


def test_audit_job_main_fetch_is_not_shallow() -> None:
    resolve = next(
        step for step in _audit_job_steps() if step.get("name") == "Resolve origin HEAD"
    )
    run = resolve["run"]
    assert "--depth" not in run, (
        "the explicit main fetch must not be shallow — P5.6 walks the last "
        "100 commits of origin/main"
    )
    assert "origin main:refs/remotes/origin/main" in run
    assert "symbolic-ref" in run  # P5.5 needs origin/HEAD


def test_baseline_is_a_branch_independent_date_baseline() -> None:
    from scripts.hydraflow_audit.checks.p10_tdd import (
        _DATE_BASELINE_RE,
        _read_baseline,
    )

    baseline = _read_baseline(REPO_ROOT)
    assert baseline is not None, ".hydraflow-audit-baseline missing or empty"
    assert _DATE_BASELINE_RE.match(baseline), (
        f"baseline {baseline!r} is SHA-shaped; the audit runs on staging PR "
        "merge commits AND on main, and no fresh SHA is an ancestor of both"
    )
