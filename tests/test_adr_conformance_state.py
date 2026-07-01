"""Config defaults + state accessors for AdrConformanceLoop (ADR-0100).

Mirrors the sibling ADR-0056 touchpoint-auditor config flags and
adr_audit_*/adr_rollup_* state methods, renamed to the adr_conformance_*
namespace so counters never collide between the two auditors.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import HydraFlowConfig
from state import StateTracker


@pytest.fixture
def state_tracker(tmp_path: Path) -> StateTracker:
    return StateTracker(tmp_path / "state.json")


def test_config_defaults():
    c = HydraFlowConfig()
    assert c.adr_conformance_loop_enabled is False
    assert c.adr_conformance_interval == 86400


def test_state_attempt_counter_increments(state_tracker: StateTracker):
    assert state_tracker.inc_adr_conformance_attempts("ADR-0049") == 1
    assert state_tracker.inc_adr_conformance_attempts("ADR-0049") == 2
    state_tracker.clear_adr_conformance_attempts("ADR-0049")
    assert state_tracker.inc_adr_conformance_attempts("ADR-0049") == 1


def test_state_attempt_counter_is_namespaced_from_adr_audit(
    state_tracker: StateTracker,
):
    """Conformance counters must not collide with the sibling audit counters."""
    state_tracker.inc_adr_audit_attempts("ADR-0049")
    state_tracker.inc_adr_audit_attempts("ADR-0049")
    assert state_tracker.inc_adr_conformance_attempts("ADR-0049") == 1


def test_state_rollup_round_trip(state_tracker: StateTracker):
    assert state_tracker.get_adr_conformance_rollup("ADR-0049") is None

    state_tracker.set_adr_conformance_rollup("ADR-0049", issue_number=1234)
    rollup = state_tracker.get_adr_conformance_rollup("ADR-0049")
    assert rollup is not None
    assert rollup["issue_number"] == 1234

    state_tracker.clear_adr_conformance_rollup("ADR-0049")
    assert state_tracker.get_adr_conformance_rollup("ADR-0049") is None


def test_state_rollup_persists_across_reload(tmp_path: Path):
    state_file = tmp_path / "state.json"
    tracker = StateTracker(state_file)
    tracker.set_adr_conformance_rollup("ADR-0049", issue_number=42)

    tracker2 = StateTracker(state_file)
    rollup = tracker2.get_adr_conformance_rollup("ADR-0049")
    assert rollup is not None
    assert rollup["issue_number"] == 42
