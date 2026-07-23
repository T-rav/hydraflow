"""Unit tests for the pure steering-actuator decision helper (Task 6).

`apply_steering` translates a per-issue `SteeringState` (Task 3) into a
`SteeringDecision` the orchestrator enacts at the phase boundary: skip
(pause), park (abort), redo (re-enqueue to a named phase), and/or guidance
passthrough for prompt fencing. No I/O; pure decision logic only.
"""

from human_steering import SteeringDecision, apply_steering
from models import SteeringState

KNOWN = {"shape", "plan", "implement", "review"}


def test_paused_issue_is_skipped():
    d = apply_steering(SteeringState(flow="paused"), "5", KNOWN, 3)

    assert d.skip is True and d.park is False and d.redo_phase is None


def test_abort_parks():
    d = apply_steering(SteeringState(flow="abort"), "5", KNOWN, 3)

    assert d.park is True


def test_redo_valid_phase_under_cap():
    d = apply_steering(SteeringState(redo_phase="shape", redo_count=1), "5", KNOWN, 3)

    assert d.redo_phase == "shape" and d.new_redo_count == 2


def test_redo_over_cap_ignored():
    d = apply_steering(SteeringState(redo_phase="shape", redo_count=3), "5", KNOWN, 3)

    assert d.redo_phase is None


def test_redo_invalid_phase_ignored():
    d = apply_steering(SteeringState(redo_phase="bogus"), "5", KNOWN, 3)

    assert d.redo_phase is None


def test_guidance_passthrough_for_fencing():
    d = apply_steering(SteeringState(guidance="focus X"), "5", KNOWN, 3)

    assert d.guidance == "focus X" and d.skip is False


def test_returns_steering_decision_instance():
    d = apply_steering(SteeringState(), "5", KNOWN, 3)

    assert isinstance(d, SteeringDecision)
