# tests/test_adr_conformance_coverage.py
"""Coverage ratchet (ADR-0098): every Accepted ADR declares Enforcement,
and every `enforced` check resolves and is side-effect-free. Mirrors
tests/test_loop_fitness_completeness.py. _GRANDFATHERED SHRINKS only.
"""

from __future__ import annotations

from pathlib import Path

from adr_conformance import classify_enforcement, is_mutating, resolve_check
from adr_index import scan_adr_directory

REPO = Path(__file__).resolve().parent.parent
ADR_DIR = REPO / "docs" / "adr"

# Fixed snapshot of every Accepted ADR number that was NOT annotated as of
# Task 4 (the ratchet's introduction). NEVER edit this literal — it is the
# baseline the subset guard below checks against. Backfill tasks shrink the
# *live* grandfathered set by adding numbers to `_ANNOTATED`, not by editing
# this frozenset.
_GRANDFATHER_BASELINE: frozenset[int] = frozenset(
    {
        1,
        2,
        3,
        4,
        5,
        7,
        8,
        9,
        10,
        11,
        12,
        14,
        15,
        16,
        17,
        18,
        19,
        21,
        22,
        23,
        24,
        25,
        27,
        31,
        32,
        34,
        35,
        36,
        37,
        41,
        42,
        43,
        45,
        47,
        49,
        50,
        51,
        52,
        56,
        64,
        83,
        88,
        89,
        94,
        95,
        96,
    }
)

# ADRs annotated with **Enforcement:** by backfill tasks, removed from the
# live grandfathered set. Task 13 annotates 0002/0003/0042/0056/0093; later
# backfill tasks (14, 15, 16) grow this set as they annotate more ADRs.
_ANNOTATED: frozenset[int] = frozenset({2, 3, 42, 56, 93})

# Live grandfathered set: baseline minus everything annotated so far. A true
# subset of the baseline, so it can only shrink — never grow, and never swap
# one exemption for another same-size one.
_GRANDFATHERED: frozenset[int] = _GRANDFATHER_BASELINE - _ANNOTATED


def _accepted():
    return [a for a in scan_adr_directory(ADR_DIR) if a.status == "Accepted"]


def test_every_accepted_adr_declares_enforcement():
    offenders = [
        a.number
        for a in _accepted()
        if a.number not in _GRANDFATHERED
        and classify_enforcement(a.enforcement) is None
    ]
    assert not offenders, f"ADRs missing/invalid **Enforcement:** {offenders}"


def test_enforced_adrs_name_resolvable_nonmutating_checks():
    problems: list[str] = []
    for a in _accepted():
        if a.number in _GRANDFATHERED or a.enforcement != "enforced":
            continue
        if not a.enforced_by:
            problems.append(f"ADR-{a.number:04d}: enforced but no Enforced-by")
            continue
        for chk in a.enforced_by:
            if chk.kind == "prose":
                problems.append(
                    f"ADR-{a.number:04d}: prose check under enforced ({chk.raw!r})"
                )
            elif is_mutating(chk):
                problems.append(
                    f"ADR-{a.number:04d}: mutating target {chk.target!r} not allowed"
                )
            elif not resolve_check(chk, REPO):
                problems.append(f"ADR-{a.number:04d}: unresolved check {chk.raw!r}")
    assert not problems, "\n".join(problems)


def test_manual_adrs_have_a_process_pointer():
    offenders = [
        a.number
        for a in _accepted()
        if a.number not in _GRANDFATHERED
        and a.enforcement == "manual"
        and not a.enforced_by
    ]
    assert not offenders, f"manual ADRs missing an Enforced-by pointer: {offenders}"


def test_grandfather_only_shrinks():
    assert _GRANDFATHERED <= _GRANDFATHER_BASELINE, (
        "_GRANDFATHERED is not a subset of _GRANDFATHER_BASELINE — exempting an "
        "ADR from the conformance ratchet is meta-level rubber-stamping. "
        "Annotate the ADR instead of swapping one exemption for another."
    )
    assert len(_GRANDFATHER_BASELINE) == 46, (
        "_GRANDFATHER_BASELINE changed size — it is a fixed snapshot from Task 4 "
        "and must never be edited. Shrink the live grandfathered set by adding "
        "annotated ADR numbers to _ANNOTATED instead."
    )
