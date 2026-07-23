"""Regression pins for issue #10038 — scheduling model as a selectable strategy.

#10038 is a design ticket: it ships the v2 IssueDriver runtime phase spec that
ADR-0099 assumes, advances ADR-0099 from Proposed to Accepted, and makes the
ADR-0002 crash-safety resolution explicit. There is no runtime knob yet (the
build follows in P2), so the invariants worth pinning are the ones a future
edit could silently regress:

1. **ADR-0099 stays a valid Accepted ADR.** Flipping it from Proposed to
   Accepted put it under the ADR-0100 conformance ratchet. If a later edit
   breaks its ``**Enforcement:**`` declaration or points ``**Enforced by:**``
   at a check that no longer resolves (or a mutating target), the ratchet in
   ``tests/test_adr_conformance_coverage.py`` fails — but this pin fails first
   and names #10038 as the reason, so the coupling is not a mystery.

2. **The phase spec resolves the ADR-0002 tension explicitly.** The whole point
   of #10038 was that ``issue_controller`` must be shown to be an execution-model
   change only, with labels still written at every phase boundary, so ADR-0002's
   crash-safety guarantee survives. If the spec loses that constraint the design
   deliverable is hollow.

3. **The spec's state machine cites a driver state layer that still exists.**
   The spec describes the machine over ``DriverState`` / ``SuspendRecord`` /
   ``PolicyEvent`` / ``ConvergenceLedger`` (the landed P1 layer). A models
   refactor that drops a driver state or field would strand the spec's
   references; this pin keeps that a conscious change.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import get_args

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from adr_conformance import classify_enforcement, is_mutating, resolve_check
from adr_index import scan_adr_directory
from models import ConvergenceLedger, DriverState, PolicyEvent, SuspendRecord

_REPO = Path(__file__).resolve().parent.parent.parent
_ADR_DIR = _REPO / "docs" / "adr"
_SPEC = (
    _REPO
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-07-20-issue-driver-v2-runtime-phase-spec-design.md"
)


def _adr_0099():
    for adr in scan_adr_directory(_ADR_DIR):
        if adr.number == 99:
            return adr
    raise AssertionError("ADR-0099 not found by scan_adr_directory")


def test_adr_0099_is_accepted_with_a_resolvable_nonmutating_enforced_check() -> None:
    adr = _adr_0099()
    assert adr.status == "Accepted", adr.status
    assert classify_enforcement(adr.enforcement) is not None
    assert adr.enforcement == "enforced"
    assert adr.enforced_by, "enforced ADR-0099 must name at least one check"
    for check in adr.enforced_by:
        assert check.kind != "prose", check.raw
        assert not is_mutating(check, _REPO), check.raw
        assert resolve_check(check, _REPO), check.raw


def test_phase_spec_resolves_the_adr_0002_crash_safety_tension_explicitly() -> None:
    text = _SPEC.read_text()
    # The three load-bearing claims of the resolution, verbatim.
    assert "label-at-every-boundary" in text
    assert "execution-model change only" in text
    assert "ADR-0002 survives intact" in text
    # Both scheduling models are named, so the spec covers the axis, not one end.
    assert "phase_requeue" in text
    assert "issue_controller" in text


def test_spec_state_machine_cites_a_driver_state_layer_that_still_exists() -> None:
    states = set(get_args(DriverState))
    expected = {
        "TRIAGE",
        "PLAN",
        "READY",
        "REVIEW",
        "HITL_WAIT",
        "HITL_APPLY",
        "DIAGNOSE",
        "PARKED",
        "MERGED",
        "CLOSED",
        "ESCALATED",
    }
    assert states == expected, states

    ledger_fields = ConvergenceLedger.model_fields
    for field in ("driver_state", "suspend", "policy_log", "route_backs"):
        assert field in ledger_fields, field
    assert "resume_state" in SuspendRecord.model_fields
    assert {"from_state", "to_state"} <= set(PolicyEvent.model_fields)
