"""Regression (#10894): a branch-protection drift that includes an undeclared
live context must NOT prescribe the bare ``--apply`` remediation.

``BranchProtectionAuditorLoop._issue_body`` hardcoded ``make gen-gates &&
setup_branch_protection.py --apply`` for every drift. When the drift includes an
undeclared legacy branch-protection context (live *requires* a check the contract
never declared), ``_apply_rulesets`` PUTs the canonical payload verbatim and
silently de-requires that live context — exactly how #10672's ``CI Gate``
umbrella (the #10663 red-PR guard) would be dropped. A factory agent auto-runs
whatever the issue prescribes, so prescribing ``--apply`` here is the bug. This
pins the declare-first routing at the marker the auditor actually emits.
"""

from __future__ import annotations

from branch_protection_audit import UNDECLARED_CONTEXT_MARKER, AuditReport
from branch_protection_auditor_loop import _issue_body

_BARE_APPLY = "make gen-gates\npython scripts/setup_branch_protection.py --apply"


def test_undeclared_context_drift_does_not_prescribe_bare_apply() -> None:
    report = AuditReport(
        repo="o/r",
        drifts=[
            f"[staging] {UNDECLARED_CONTEXT_MARKER} required live but not in "
            "the declarative contract: CI Gate"
        ],
    )
    body = _issue_body(report)
    # De-require hazard: the bare reapply block must not be the remediation.
    assert _BARE_APPLY not in body
    # Instead: declare the missing gate in the contract first.
    assert "gates.toml" in body
    assert "ADDING-A-GATE" in body


def test_normal_drift_still_prescribes_reapply() -> None:
    report = AuditReport(repo="o/r", drifts=["[main protect] canonical/live differ"])
    assert _BARE_APPLY in _issue_body(report)
