"""Unenforced-decision-debt ratchet (issue #10411).

ADR-0100 already requires every Accepted ADR to *declare* an
``**Enforcement:**`` kind and, for ``enforced`` ADRs, that the cited checks
RESOLVE. What it does NOT do is push the *debt* down: an ADR can freely
declare ``manual`` / ``decision-of-record`` and cite no runnable check at all.
That is the tail the citation-drift firehose was flooding over.

This ratchet inverts the signal. Every Accepted ADR must have a REAL
enforcement (``has_real_enforcement`` — ADR-0100's ``enforced`` bar) UNLESS it
is grandfathered in ``_DEBT_BASELINE``. The baseline is a fixed snapshot of the
debt that existed when this ratchet landed; it may only SHRINK (by moving a
paid-off ADR into ``_RESOLVED``), never grow and never swap one exemption for
another. So a NEW Accepted ADR must bind its decision to a real check, and the
existing tail can only get smaller. The live tally is surfaced in
``docs/arch/generated/adr-enforcement.md``.

Mirrors ``tests/test_adr_conformance_coverage.py``'s grandfather discipline.
The *assertion-strength* (tautological-check) signal is intentionally NOT
ratcheted here — it is advisory-only in the debt report, because a
conservative heuristic must never gate CI on its own false positives.
"""

from __future__ import annotations

from pathlib import Path

from adr_conformance import (
    EnforcementClass,
    classify_adr_enforcement,
    has_real_enforcement,
)
from adr_index import scan_adr_directory

REPO = Path(__file__).resolve().parents[2]
ADR_DIR = REPO / "docs" / "adr"

# Fixed snapshot of the unenforced-decision debt as of this ratchet landing:
# every Accepted ADR that was WEAK (manual prose pointer) or MISSING (bare
# decision-of-record). NEVER edit this literal — it is the baseline the
# subset guard below checks against. Pay debt down by adding numbers to
# ``_RESOLVED`` (which shrinks the live grandfathered set), not by editing it.
#   manual (WEAK):            9, 23, 25, 35, 42, 51, 65
#   decision-of-record (MISSING): 3, 27, 30, 91, 107
_DEBT_BASELINE: frozenset[int] = frozenset(
    {3, 9, 23, 25, 27, 30, 35, 42, 51, 65, 91, 107}
)

# ADRs from the baseline that have since been given a REAL enforcement and so
# are removed from the live grandfathered set. Grows over time; starts empty.
_RESOLVED: frozenset[int] = frozenset()

# Live grandfathered set: a true subset of the baseline, so it can only shrink.
_GRANDFATHERED: frozenset[int] = _DEBT_BASELINE - _RESOLVED


def _accepted():
    return [a for a in scan_adr_directory(ADR_DIR) if a.status == "Accepted"]


def test_new_accepted_adrs_have_real_enforcement():
    """Any Accepted ADR not grandfathered must bind its decision to a REAL,
    resolving, non-mutating check (ADR-0100's ``enforced`` bar)."""
    offenders = [
        a.number
        for a in _accepted()
        if a.number not in _GRANDFATHERED and not has_real_enforcement(a, REPO)
    ]
    assert not offenders, (
        f"Accepted ADR(s) {offenders} declare no REAL enforcement and are not "
        "grandfathered. Bind the decision to a runnable check: set "
        "`**Enforcement:** enforced` and cite a resolving, non-mutating "
        "`**Enforced by:** pytest:tests/...::Test...` (or `make:<target>`). "
        "See docs/arch/generated/adr-enforcement.md for the live debt tally. "
        "New decisions must be enforceable — the drift firehose is not a "
        "substitute for a real check."
    )


def test_grandfather_only_shrinks():
    assert _GRANDFATHERED <= _DEBT_BASELINE, (
        "_GRANDFATHERED is not a subset of _DEBT_BASELINE — exempting an ADR "
        "from the enforcement-debt ratchet is meta-level rubber-stamping. "
        "Enforce the ADR (and add it to _RESOLVED) instead of swapping one "
        "exemption for another."
    )
    assert len(_DEBT_BASELINE) == 12, (
        "_DEBT_BASELINE changed size — it is a fixed snapshot of the "
        "unenforced-decision debt at ratchet-landing and must never be edited. "
        "Shrink the live grandfathered set by adding paid-off ADR numbers to "
        "_RESOLVED instead."
    )


def test_resolved_adrs_are_genuinely_enforced_now():
    """Every ADR claimed as _RESOLVED must actually be REAL now — you cannot
    drop an exemption without having paid the debt."""
    live = {a.number: a for a in _accepted()}
    regressed = [
        n
        for n in sorted(_RESOLVED)
        if n in live
        and classify_adr_enforcement(live[n], REPO) is not EnforcementClass.REAL
    ]
    assert not regressed, (
        f"ADR(s) {regressed} are listed in _RESOLVED but no longer classify "
        "REAL — their enforcement regressed. Restore the real check or move "
        "them back out of _RESOLVED."
    )


def test_grandfathered_adrs_still_unenforced_get_flagged_to_shrink():
    """A grandfathered ADR that has since GAINED a real enforcement must be
    moved into _RESOLVED — the ratchet only earns its keep if the debt is
    actively drained as it is paid."""
    live = {a.number: a for a in _accepted()}
    now_real = sorted(
        n for n in _GRANDFATHERED if n in live and has_real_enforcement(live[n], REPO)
    )
    assert not now_real, (
        f"Grandfathered ADR(s) {now_real} now have a REAL enforcement — move "
        "them from the grandfathered set into _RESOLVED so the debt baseline "
        "reflects reality and can never silently re-inflate."
    )
