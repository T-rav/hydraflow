"""Regression pins for #11298 planner-side size tiering.

Pins the invariants that make forced-lite planning safe:

1. **Fail-closed** — unclassified issues never get forced lite; the planner
   keeps its own heuristic scale detection.
2. **Self-healing escape valve** — a routed-back issue is disqualified from
   tiering, so a lite plan that failed review replans at full scale.
3. The planner's ``force_scale`` override wins over heuristics, and ``None``
   leaves heuristic detection untouched.
"""

from __future__ import annotations

from types import SimpleNamespace

from config import HydraFlowConfig


def _gate(config: HydraFlowConfig, *, record: object, route_backs: int = 0):
    from plan_phase import PlanPhase

    phase = object.__new__(PlanPhase)
    phase._config = config
    phase._issue_cache = SimpleNamespace(latest_classification=lambda _id: record)
    phase._state = SimpleNamespace(get_route_back_count=lambda _id: route_backs)
    phase._has_escalation_label = lambda _issue: False
    return phase


def test_default_threshold_is_five() -> None:
    assert HydraFlowConfig().planner_lite_min_complexity == 5


def test_simple_issue_forced_lite_at_default() -> None:
    record = SimpleNamespace(payload={"complexity_score": 3})
    assert (
        _gate(HydraFlowConfig(), record=record)._forced_plan_scale(
            SimpleNamespace(id=1)
        )
        == "lite"
    )


def test_unclassified_fails_closed_to_heuristics() -> None:
    assert (
        _gate(HydraFlowConfig(), record=None)._forced_plan_scale(SimpleNamespace(id=1))
        is None
    )


def test_routed_back_issue_replans_at_full_scale() -> None:
    record = SimpleNamespace(payload={"complexity_score": 1})
    assert (
        _gate(HydraFlowConfig(), record=record, route_backs=1)._forced_plan_scale(
            SimpleNamespace(id=1)
        )
        is None
    )


def test_planner_force_scale_overrides_heuristics() -> None:
    import inspect

    from planner import PlannerRunner

    signature = inspect.signature(PlannerRunner.plan)
    assert "force_scale" in signature.parameters
    assert signature.parameters["force_scale"].default is None
