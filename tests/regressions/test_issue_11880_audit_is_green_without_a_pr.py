"""`make audit` outside a PR context must not be red (#11880 follow-up).

P10.8 — the test-pyramid gate shipped in #11897 — is scoped to PR CI by design:
it judges the change under review against the standard's matrix and reuses
P10.6's merge-base diff. With no PR context there is no change to judge, so it
returns NA. Correct.

But `runner._classify_na` downgrades an NA with no entry in `NA_JUSTIFICATIONS`
to **INERT**, because the audit cannot otherwise tell a subject that
legitimately does not apply from one that silently VANISHED — the failure that
let P2.3/P2.4/P2.6/P2.7 stay green from the day they merged. INERT counts as a
red audit in `overall_exit_code`.

P10.8 shipped without that entry, so every local `make audit` — the command
CLAUDE.md tells every contributor to run before declaring work complete — began
exiting 2 with `INERT 1`.

**CI never saw it.** The Principles Audit job sets `HYDRAFLOW_AUDIT_PR_BASE`, so
P10.8 ran there and never reported NA. Green in CI, red on every developer's
machine, and green precisely where it was tested.

The guard is not "P10.8 has a key" — that is a spelling check on one dictionary
entry, and it would pass forever while the next check with an NA path repeats
the defect. It asserts the property: **every registered check that reports NA
carries a justification**, derived from the registry the runner actually
consults.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "src"))

from hydraflow_audit.models import Finding, Severity, Status
from hydraflow_audit.na_justifications import NA_JUSTIFICATIONS
from hydraflow_audit.runner import _classify_na, overall_exit_code


def _na(check_id: str) -> Finding:
    """An NA finding shaped exactly as a check returns one."""
    return Finding(
        check_id=check_id,
        status=Status.NA,
        severity=Severity.STRUCTURAL,
        principle="P10",
        source="docs/standards/testing/README.md",
        what="the test pyramid",
        remediation="",
        message="not a PR context (HYDRAFLOW_AUDIT_PR_BASE unset)",
    )


def test_the_pyramid_gate_na_is_justified_not_inert() -> None:
    """The exact regression: P10.8 reporting NA must survive classification."""
    classified = _classify_na(_na("P10.8"))

    assert classified.status is Status.NA, (
        "P10.8's NA was downgraded to INERT — every local `make audit` outside "
        "a PR context is red"
    )
    assert overall_exit_code([classified]) == 0


def test_an_unregistered_na_is_still_inert() -> None:
    """Anti-vacuity: the registry must not become decoration.

    Without this, deleting `_classify_na`'s check entirely would satisfy the
    test above while re-admitting the P2.3/P2.4/P2.6/P2.7 defect it exists to
    prevent — a check whose subject vanished reporting NA and passing.
    """
    classified = _classify_na(_na("P99.9-not-a-real-check"))

    assert classified.status is Status.INERT
    assert overall_exit_code([classified]) != 0


def test_every_pr_scoped_check_that_can_report_na_is_registered() -> None:
    """Derived from the checks that share P10.6's PR-context precondition.

    Named by reference rather than spelled: P10.6 and P10.8 both return NA when
    `HYDRAFLOW_AUDIT_PR_BASE` is unset, and any future check reusing
    `_pr_gate_preflight` inherits that path. A test naming only P10.8 would
    pass forever and never see the next one.
    """
    import inspect

    from hydraflow_audit.checks import p10_tdd

    src = inspect.getsource(p10_tdd)
    pr_scoped = {
        cid for cid in ("P10.6", "P10.8") if f'"{cid}"' in src or f"'{cid}'" in src
    }
    assert pr_scoped == {"P10.6", "P10.8"}, (
        f"the PR-scoped check set changed; re-derive this guard: {pr_scoped}"
    )
    missing = pr_scoped - set(NA_JUSTIFICATIONS)
    assert not missing, (
        "PR-scoped checks that report NA outside a PR context, with no "
        f"NA_JUSTIFICATIONS entry (each makes `make audit` red locally): {missing}"
    )
