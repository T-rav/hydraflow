"""Regression pins for #11298 size-tiered plan review.

The tier gate trades plan-stage ceremony for tokens on simple issues; these
pins protect the two invariants that make that trade safe:

1. **READY-gate invariant** — a skipped review MUST still write a
   ``review_stored`` record (``has_blocking=False``), or the READY-stage
   precondition routes every light-tier issue straight back to plan.
2. **Fail-closed default** — an issue the gate cannot read (no cache, no
   classification, malformed payload) is treated as maximally complex and
   ALWAYS reviewed. Tiering may only ever skip on positive evidence.
"""

from __future__ import annotations

from types import SimpleNamespace

from config import HydraFlowConfig


def _gate(config: HydraFlowConfig, *, record: object, route_backs: int = 0):
    """A minimal PlanPhase carrying just what _skip_plan_review touches."""
    from plan_phase import PlanPhase

    phase = object.__new__(PlanPhase)
    phase._config = config
    phase._issue_cache = SimpleNamespace(latest_classification=lambda _id: record)
    phase._state = SimpleNamespace(get_route_back_count=lambda _id: route_backs)
    phase._has_escalation_label = lambda _issue: False
    return phase


def _classified(score: object) -> SimpleNamespace:
    return SimpleNamespace(payload={"complexity_score": score})


def test_default_threshold_is_five() -> None:
    assert HydraFlowConfig().plan_review_min_complexity == 5


def test_simple_issue_skips_at_default_threshold() -> None:
    phase = _gate(HydraFlowConfig(), record=_classified(3))
    skip, complexity = phase._skip_plan_review(SimpleNamespace(id=1))
    assert skip is True
    assert complexity == 3


def test_unclassified_issue_fails_closed_to_full_review() -> None:
    phase = _gate(HydraFlowConfig(), record=None)
    skip, complexity = phase._skip_plan_review(SimpleNamespace(id=1))
    assert skip is False
    assert complexity == 10


def test_malformed_payload_fails_closed_to_full_review() -> None:
    for record in (
        SimpleNamespace(payload=None),
        SimpleNamespace(payload={"complexity_score": "not-a-number"}),
        SimpleNamespace(no_payload_attr=True),
    ):
        phase = _gate(HydraFlowConfig(), record=record)
        skip, complexity = phase._skip_plan_review(SimpleNamespace(id=1))
        assert skip is False
        assert complexity == 10


def test_cycled_issue_never_skips() -> None:
    phase = _gate(HydraFlowConfig(), record=_classified(1), route_backs=1)
    skip, _complexity = phase._skip_plan_review(SimpleNamespace(id=1))
    assert skip is False


def test_escalation_labeled_issue_never_skips() -> None:
    phase = _gate(HydraFlowConfig(), record=_classified(1))
    phase._has_escalation_label = lambda _issue: True
    skip, _complexity = phase._skip_plan_review(SimpleNamespace(id=1))
    assert skip is False


def test_zero_threshold_disables_tiering() -> None:
    config = HydraFlowConfig(plan_review_min_complexity=0)
    phase = _gate(config, record=_classified(1))
    skip, _complexity = phase._skip_plan_review(SimpleNamespace(id=1))
    assert skip is False
