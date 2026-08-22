"""Regression for #11533: stale Discover/Shape driver states cannot return.

ADR-0107 collapsed Discover and Shape into planner-invoked helpers. The
IssueDriver v2 spec nevertheless kept describing a 13-state ``DriverState``
including both, so a plan written against it would have rebuilt retired
stages. These pins hold the driver surface — the state literal, the contract
phase enum, the worker catalog, and the spec's own transition map — to the
live Triage -> Plan -> Implement -> Review -> HITL topology.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import pytest

from driver_contracts import WORKER_CATALOG, DriverPhase
from models import DriverState

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-07-20-issue-driver-v2-runtime-phase-spec-design.md"
)
ADR = (
    REPO_ROOT
    / "docs"
    / "adr"
    / "0137-fenced-issue-driver-and-director-runtime-boundary.md"
)
ADR_0094 = REPO_ROOT / "docs" / "adr" / "0094-two-level-convergence-gate-and-ledger.md"

RETIRED_STATES = ("DISCOVER", "SHAPE")


# --------------------------------------------------------------------------
# The live state surface
# --------------------------------------------------------------------------


@pytest.mark.parametrize("retired", RETIRED_STATES)
def test_driver_state_literal_has_no_retired_stage(retired: str) -> None:
    assert retired not in get_args(DriverState)


def test_driver_state_literal_is_the_eleven_live_states() -> None:
    assert len(get_args(DriverState)) == 11


@pytest.mark.parametrize("retired", RETIRED_STATES)
def test_driver_phase_enum_has_no_retired_stage(retired: str) -> None:
    assert retired not in {phase.name for phase in DriverPhase}


def test_driver_phase_enum_is_the_five_live_dispatchable_phases() -> None:
    assert {p.name for p in DriverPhase} == {
        "TRIAGE",
        "PLAN",
        "IMPLEMENT",
        "REVIEW",
        "HITL",
    }


def test_every_driver_phase_is_a_live_driver_state_or_its_stage_alias() -> None:
    # IMPLEMENT is the driver-phase name for the READY state / hydraflow-ready label;
    # HITL covers HITL_WAIT and HITL_APPLY. Everything else must match one-to-one.
    states = set(get_args(DriverState))
    aliased = {"IMPLEMENT": "READY", "HITL": "HITL_WAIT"}

    unmapped = [
        p.name for p in DriverPhase if aliased.get(p.name, p.name) not in states
    ]

    assert unmapped == []


@pytest.mark.parametrize("retired", RETIRED_STATES)
def test_no_worker_catalog_entry_targets_a_retired_stage(retired: str) -> None:
    phases = {
        phase.name
        for entry in WORKER_CATALOG.values()
        for phase in entry.allowed_phases
    }

    assert retired not in phases


# --------------------------------------------------------------------------
# The spec that described the retired stages
# --------------------------------------------------------------------------


def _transition_map_line() -> str:
    for line in SPEC.read_text().splitlines():
        if line.startswith("**Transition map (nominal path):**"):
            return line
    raise AssertionError("spec no longer declares a transition map")


@pytest.mark.parametrize("retired", RETIRED_STATES)
def test_spec_transition_map_has_no_retired_stage(retired: str) -> None:
    assert retired not in _transition_map_line()


def test_spec_transition_map_states_the_live_nominal_path() -> None:
    assert "`TRIAGE → PLAN → READY → REVIEW → MERGED`" in _transition_map_line()


def test_spec_declares_the_eleven_state_literal() -> None:
    assert "**11-state** literal" in SPEC.read_text()


def test_spec_no_longer_claims_a_thirteen_state_literal() -> None:
    # The realignment blockquote may recount the old 13-state literal as history;
    # no live (unquoted) line may still assert it.
    live_claims = [
        line
        for line in SPEC.read_text().splitlines()
        if "13-state" in line and not line.lstrip().startswith(">")
    ]

    assert live_claims == []


# --------------------------------------------------------------------------
# The constraints and evidence #11533 required
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "heading",
    [
        "### 5.5 Reconcile-from-label (Constraint C5)",
        "### 5.6 Capacity release for non-working drivers (Constraint C6)",
        "### 5.7 SchedulingPolicy / SchedulingView, and the P0 wait bound",
        "### 5.8 Boundary transaction ordering (Constraint C8)",
        '## 8a. The quantitative "proven" bar',
        "## 8b. Alternatives considered",
    ],
)
def test_spec_retains_the_section_that_answers_an_adversarial_finding(
    heading: str,
) -> None:
    assert heading in SPEC.read_text()


def test_spec_names_the_stage_priority_reconciliation_rule() -> None:
    assert "_STAGE_PRIORITY" in SPEC.read_text()


def test_spec_names_the_queue_strategy_same_day_flip_as_the_anti_pattern() -> None:
    text = SPEC.read_text()

    assert "#10061" in text and "anti-pattern" in text


# --------------------------------------------------------------------------
# The ADR that narrows ADR-0094
# --------------------------------------------------------------------------


def test_adr_0137_is_accepted() -> None:
    assert re.search(r"^\*\*Status:\*\*\s*Accepted\s*$", ADR.read_text(), re.MULTILINE)


def test_adr_0137_declares_enforced_enforcement() -> None:
    assert re.search(
        r"^\*\*Enforcement:\*\*\s*enforced\s*$", ADR.read_text(), re.MULTILINE
    )


def test_adr_0137_names_this_regression_module_as_an_enforcing_check() -> None:
    assert (
        "pytest:tests/regressions/test_issue_11533_stale_driver_states.py"
        in ADR.read_text()
    )


def test_adr_0137_narrows_rather_than_reverses_adr_0094() -> None:
    assert "**Amends:** ADR-0094" in ADR.read_text()


def test_adr_0094_points_at_the_narrowing_adr() -> None:
    assert "Narrowed by [ADR-0137]" in ADR_0094.read_text()


def test_adr_0094_keeps_its_original_rejection_text() -> None:
    # The narrowing must scope the rejection, never erase the record of it.
    assert "Rejected in favor of requeue + ledger" in ADR_0094.read_text()


@pytest.mark.parametrize(
    "finding", ["**B1 —", "**B2 —", "**B3 —", "**B4 —", "**B5 —", "**B6 —", "**B7 —"]
)
def test_adr_0137_answers_each_adversarial_finding(finding: str) -> None:
    assert finding in ADR.read_text()


def test_adr_0137_records_the_sandbox_verification_constraint() -> None:
    # The condition the conditional GO rests on.
    assert "SANDBOX_UNVERIFIED" in ADR.read_text()
