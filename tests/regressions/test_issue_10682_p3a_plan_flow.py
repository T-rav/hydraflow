"""Regression pins for P3a of epic #10682 — the plan phase on the flow primitive.

``PlanPhase._plan_one`` is a structural refactor onto the P0 ``src/flows`` DAG
runtime (ADR-0111): the same per-issue plan pipeline, now expressed as an
explicit ``Node``/``Edge`` graph

    prepass -> surface -> draft -> ensemble -> route
        route        --(close / escalate / plain-failure)--> done
        route        --> write-records -> gate
        gate         --(design-decision concerns >= K)------> done  (human-required)
        gate         --> ready -> done

instead of a straight-line method. Plan is a core phase and this ships with NO
feature flag, so parity is the only safety net.

These tests pin the load-bearing invariants of that cutover:

1. **Flow shape / node order.** A successful plan walks
   ``prepass -> surface -> draft -> ensemble -> route -> write-records -> gate ->
   ready -> done`` with the planner (LLM actuator) confined to ``draft``.
2. **Output parity.** The flow-backed public entry transitions a seeded plan to
   ``hydraflow-ready`` and returns the planner's ``PlanResult``.
3. **Design-decision gate (#10659).** N>=K design-decision-class CRITICAL
   concerns route to ``human-required`` via the explicit ``gate`` node, NOT to
   ready; ordinary implementer-addressable concerns still reach ready.
4. **Blocking review records the route-back signal.** A blocking plan review is
   recorded with ``has_blocking=True`` (the signal the downstream READY-stage
   gate uses to route back to plan) — plan itself still swaps to ready.
5. **Plan failure.** A failed plan never swaps to ready and walks straight to the
   terminal ``done`` sink.

If any regress, the converted phase could drop a step, skip the #10659 gate,
forward an underspecified design issue to implement, or silently change the
delivered ``PlanResult``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from flows import Flow
from pending_concerns import AdversarialState, Concern
from tests.conftest import PlanResultFactory, TaskFactory
from tests.helpers import make_plan_phase, supply_once

if TYPE_CHECKING:
    from config import HydraFlowConfig

pytestmark = pytest.mark.asyncio

_HAPPY_ORDER = [
    "prepass",
    "surface",
    "draft",
    "ensemble",
    "route",
    "write-records",
    "gate",
    "ready",
    "done",
]


def _is_subsequence(sub: list[str], seq: list[str]) -> bool:
    """True if *sub* appears in *seq* in order (not necessarily contiguously)."""
    it = iter(seq)
    return all(item in it for item in sub)


def _design_concern(*, stage: str, severity: str = "CRITICAL", idx: int = 1) -> Concern:
    return Concern(
        id=f"{stage.upper()}-{idx:03d}",
        raised_in_phase="plan",
        raised_in_stage=stage,
        severity=severity,  # type: ignore[arg-type]
        concern="Unvalidated core mechanism — needs a human decision.",
        raised_at=datetime.now(UTC),
        must_address_by="planner",
    )


def _success_plan(issue_id: int) -> object:
    return PlanResultFactory.create(
        issue_number=issue_id,
        success=True,
        plan="The plan",
        summary="Done",
        use_defaults=True,
    )


# ---------------------------------------------------------------------------
# 1. Flow shape + node order
# ---------------------------------------------------------------------------


async def test_plan_one_builds_a_flow_entered_at_prepass(
    config: HydraFlowConfig,
) -> None:
    """The per-issue pipeline is an ``src.flows.Flow`` whose entry is ``prepass``."""
    phase, _state, _planners, _prs, _store, _stop = make_plan_phase(config)

    flow = phase._build_plan_flow()

    assert isinstance(flow, Flow)
    assert flow.entry == "prepass"


async def test_happy_path_node_order_confines_planner_to_draft(
    config: HydraFlowConfig,
) -> None:
    """A successful plan walks the documented node order; planner runs in draft."""
    issue = TaskFactory.create(id=7001)
    phase, _state, planners, _prs, _store, _stop = make_plan_phase(config)
    planners.plan = AsyncMock(return_value=_success_plan(7001))

    recorded: list[str] = []
    flow = phase._build_plan_flow(
        checkpoint=lambda name, _state: recorded.append(name)
    )
    result = await flow.run(phase._initial_plan_state(0, issue))

    assert _is_subsequence(_HAPPY_ORDER, result.path)
    # Checkpoint fires once per node, in walk order (the resume substrate).
    assert recorded == result.path
    assert result.terminal == "done"
    # The planner (LLM actuator) fires exactly once, and only at ``draft`` —
    # before ``ensemble`` and after ``surface``.
    planners.plan.assert_awaited_once()
    assert recorded.index("draft") < recorded.index("ensemble")
    assert recorded.index("surface") < recorded.index("draft")
    assert result.state["result"] is planners.plan.return_value


# ---------------------------------------------------------------------------
# 2. Output parity — happy path transitions to ready
# ---------------------------------------------------------------------------


async def test_happy_path_transitions_to_ready(config: HydraFlowConfig) -> None:
    """A seeded successful plan swaps to hydraflow-ready (full plan_issues path)."""
    issue = TaskFactory.create(id=7002)
    phase, _state, planners, prs, store, _stop = make_plan_phase(config)
    planners.plan = AsyncMock(return_value=_success_plan(7002))
    store.get_plannable = supply_once([issue])

    await phase.plan_issues()

    prs.transition.assert_awaited_once_with(7002, "ready")
    prs.swap_pipeline_labels.assert_not_awaited()


# ---------------------------------------------------------------------------
# 3. Design-decision gate (#10659 preserved through the explicit gate node)
# ---------------------------------------------------------------------------


async def test_design_decision_criticals_route_to_human_required(
    config: HydraFlowConfig,
) -> None:
    """N>=K design-decision CRITICAL concerns -> human-required via the gate node."""
    issue = TaskFactory.create(id=7003)
    phase, state, planners, prs, store, _stop = make_plan_phase(config)
    state.set_adversarial_state(
        7003,
        AdversarialState(
            phase="plan",
            pending_concerns=[
                _design_concern(stage="plan_ensemble_risk_skeptic", idx=1),
                _design_concern(stage="assumption_surfacer", idx=2),
            ],
        ),
    )
    planners.plan = AsyncMock(return_value=_success_plan(7003))
    store.get_plannable = supply_once([issue])

    await phase.plan_issues()

    prs.swap_pipeline_labels.assert_awaited_once_with(7003, "human-required")
    for call in prs.transition.await_args_list:
        assert call.args != (7003, "ready")
    # Adversarial state cleared on hand-off (fresh start on re-queue).
    assert state.get_adversarial_state(7003) is None


async def test_gate_node_stops_walk_before_ready_on_design_decision(
    config: HydraFlowConfig,
) -> None:
    """The design-decision walk reaches ``gate`` then stops — never ``ready``."""
    issue = TaskFactory.create(id=7004)
    phase, state, planners, _prs, _store, _stop = make_plan_phase(config)
    state.set_adversarial_state(
        7004,
        AdversarialState(
            phase="plan",
            pending_concerns=[
                _design_concern(stage="plan_ensemble_risk_skeptic", idx=1),
                _design_concern(stage="assumption_surfacer", idx=2),
            ],
        ),
    )
    planners.plan = AsyncMock(return_value=_success_plan(7004))

    result = await phase._build_plan_flow().run(phase._initial_plan_state(0, issue))

    assert "gate" in result.path
    assert "ready" not in result.path
    assert result.terminal == "done"


async def test_ordinary_concerns_still_route_to_ready(
    config: HydraFlowConfig,
) -> None:
    """Only implementer-addressable concerns -> ready (gate is a pass-through)."""
    issue = TaskFactory.create(id=7005)
    phase, state, planners, prs, store, _stop = make_plan_phase(config)
    state.set_adversarial_state(
        7005,
        AdversarialState(
            phase="plan",
            pending_concerns=[
                _design_concern(stage="plan_ensemble_builder", severity="HIGH", idx=1),
            ],
        ),
    )
    planners.plan = AsyncMock(return_value=_success_plan(7005))
    store.get_plannable = supply_once([issue])

    await phase.plan_issues()

    prs.transition.assert_awaited_once_with(7005, "ready")
    prs.swap_pipeline_labels.assert_not_awaited()


# ---------------------------------------------------------------------------
# 4. Blocking review records the route-back signal
# ---------------------------------------------------------------------------


async def test_blocking_review_records_route_back_signal(
    config: HydraFlowConfig,
) -> None:
    """A blocking plan review is recorded has_blocking=True; plan still swaps ready.

    The plan flow records the route-back signal; the downstream READY-stage
    precondition gate is what actually routes the issue back to plan.
    """
    from models import PlanFinding, PlanFindingSeverity, PlanReview

    issue = TaskFactory.create(id=7006)
    phase, _state, planners, prs, store, _stop = make_plan_phase(config)
    planners.plan = AsyncMock(return_value=_success_plan(7006))
    store.get_plannable = supply_once([issue])

    reviewer = AsyncMock()
    reviewer.review = AsyncMock(
        return_value=PlanReview(
            issue_number=7006,
            plan_version=1,
            success=True,
            findings=[
                PlanFinding(
                    severity=PlanFindingSeverity.HIGH,
                    dimension="correctness",
                    description="missed ADR-0021 rule",
                ),
            ],
            summary="1 high finding",
        )
    )
    phase._plan_reviewer = reviewer  # type: ignore[assignment]

    recorded: dict[str, object] = {}
    cache = AsyncMock()
    cache.record_plan_stored = lambda *_a, **_kw: 1

    def _capture(*_a: object, **kw: object) -> None:
        recorded.update(kw)

    cache.record_review_stored = _capture
    phase._issue_cache = cache  # type: ignore[assignment]

    await phase.plan_issues()

    assert recorded.get("has_blocking") is True
    prs.transition.assert_awaited_once_with(7006, "ready")


# ---------------------------------------------------------------------------
# 5. Plan failure never swaps to ready
# ---------------------------------------------------------------------------


async def test_failed_plan_never_swaps_to_ready(config: HydraFlowConfig) -> None:
    """A failed plan walks to ``done`` and never reaches write-records/gate/ready."""
    issue = TaskFactory.create(id=7007)
    phase, _state, planners, prs, _store, _stop = make_plan_phase(config)
    planners.plan = AsyncMock(
        return_value=PlanResultFactory.create(
            issue_number=7007,
            success=False,
            plan="",
            error="planner failed",
            use_defaults=True,
        )
    )

    result = await phase._build_plan_flow().run(phase._initial_plan_state(0, issue))

    assert result.terminal == "done"
    assert "write-records" not in result.path
    assert "gate" not in result.path
    assert "ready" not in result.path
    for call in prs.transition.await_args_list:
        assert call.args != (7007, "ready")
