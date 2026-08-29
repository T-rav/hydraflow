"""Regression for issue #10659.

When the buildable backlog drains, the factory began pulling design/research
issues through triage -> plan -> **implement**. The plan-review adversarial
pass raised CRITICAL "needs a human design decision / unvalidated core
mechanism" concerns (e.g. #10602, #10616), but the dark-factory contract
forwarded them to implementation anyway — where the build agent hangs the full
3600s timeout and retry-thrashes on an underspecified feature.

The fix installs a guard at the plan->ready gate: when plan review accumulates
>= K design-decision-class CRITICAL concerns, the issue routes to
``human-required`` instead of swapping to ``hydraflow-ready``. Ordinary
implementer-addressable concerns (buildability / coverage / AC) still flow to
ready as before.

Root cause: ``src/plan_phase.py::PlanPhase._handle_plan_success`` swapped every
successful plan to ``ready`` regardless of the accumulated ``AdversarialState``
concerns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from pending_concerns import (
    AdversarialState,
    Concern,
    count_design_decision_concerns,
    is_design_decision_concern,
)
from tests.conftest import PlanResultFactory, TaskFactory
from tests.helpers import make_plan_phase, supply_once

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from state import StateTracker


def _concern(
    *,
    stage: str,
    severity: str,
    human_required: bool = False,
    idx: int = 1,
) -> Concern:
    return Concern(
        id=f"{stage.upper()}-{idx:03d}",
        raised_in_phase="plan",
        raised_in_stage=stage,
        severity=severity,  # type: ignore[arg-type]
        concern="Unvalidated core mechanism — needs a human decision.",
        raised_at=datetime.now(UTC),
        must_address_by="planner",
        human_required=human_required,
    )


def _seed(state: StateTracker, issue_id: int, concerns: list[Concern]) -> None:
    state.set_adversarial_state(
        issue_id,
        AdversarialState(phase="plan", pending_concerns=concerns),
    )


async def _run_plan(config: HydraFlowConfig, issue_id: int, concerns: list[Concern]):
    phase, state, planners, prs, store, _stop = make_plan_phase(config)
    _seed(state, issue_id, concerns)
    issue = TaskFactory.create(id=issue_id)
    planners.plan = AsyncMock(
        return_value=PlanResultFactory.create(
            issue_number=issue_id,
            success=True,
            plan="The plan",
            summary="Done",
            use_defaults=True,
        )
    )
    store.get_plannable = supply_once([issue])
    await phase.plan_issues()
    return state, prs


# ---------------------------------------------------------------------------
# Classifier unit tests
# ---------------------------------------------------------------------------


class TestDesignDecisionClassifier:
    def test_critical_risk_skeptic_is_design_decision(self) -> None:
        c = _concern(stage="plan_ensemble_risk_skeptic", severity="CRITICAL")
        assert is_design_decision_concern(c) is True

    def test_critical_builder_is_not_design_decision(self) -> None:
        # Buildability is implementer-addressable, not a human decision.
        c = _concern(stage="plan_ensemble_builder", severity="CRITICAL")
        assert is_design_decision_concern(c) is False

    def test_high_risk_skeptic_is_not_design_decision(self) -> None:
        # Only CRITICAL from a design-gate stage parks; HIGH still forwards.
        c = _concern(stage="plan_ensemble_risk_skeptic", severity="HIGH")
        assert is_design_decision_concern(c) is False

    def test_explicit_human_required_flag_qualifies_regardless_of_stage(self) -> None:
        c = _concern(stage="plan_ensemble_builder", severity="LOW", human_required=True)
        assert is_design_decision_concern(c) is True

    def test_count_helper_counts_only_design_decision_concerns(self) -> None:
        concerns = [
            _concern(stage="plan_ensemble_risk_skeptic", severity="CRITICAL", idx=1),
            _concern(stage="plan_ensemble_builder", severity="CRITICAL", idx=2),
            _concern(stage="assumption_surfacer", severity="CRITICAL", idx=3),
            _concern(stage="spec_judge", severity="HIGH", idx=4),
        ]
        assert count_design_decision_concerns(concerns) == 2


# ---------------------------------------------------------------------------
# Gate routing tests (through the real plan_issues() path)
# ---------------------------------------------------------------------------


class TestPlanGateRoutesDesignDecisionsToHitl:
    @pytest.mark.asyncio
    async def test_many_design_decision_criticals_route_to_human_required(
        self, config: HydraFlowConfig
    ) -> None:
        """(a) N>=K design-decision CRITICAL concerns -> human-required, NOT ready."""
        concerns = [
            _concern(stage="plan_ensemble_risk_skeptic", severity="CRITICAL", idx=1),
            _concern(stage="assumption_surfacer", severity="CRITICAL", idx=2),
        ]
        state, prs = await _run_plan(config, 10602, concerns)

        prs.swap_pipeline_labels.assert_awaited_once_with(10602, "human-required")
        # The issue must NOT be swapped to ready.
        for call in prs.transition.await_args_list:
            assert call.args != (10602, "ready"), (
                "design-decision issue must not transition to ready"
            )
        # Adversarial state cleared on hand-off (fresh start on re-queue).
        assert state.get_adversarial_state(10602) is None

    @pytest.mark.asyncio
    async def test_ordinary_fixable_concerns_still_route_to_ready(
        self, config: HydraFlowConfig
    ) -> None:
        """(b) only implementer-addressable concerns -> ready as before."""
        concerns = [
            _concern(stage="plan_ensemble_builder", severity="HIGH", idx=1),
            _concern(stage="plan_ensemble_tester", severity="CRITICAL", idx=2),
            _concern(stage="spec_judge", severity="HIGH", idx=3),
        ]
        _state, prs = await _run_plan(config, 4242, concerns)

        prs.transition.assert_awaited_once_with(4242, "ready")
        prs.swap_pipeline_labels.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_single_design_decision_critical_below_threshold_routes_to_ready(
        self, config: HydraFlowConfig
    ) -> None:
        """A lone design-decision CRITICAL (below K) still flows to ready."""
        concerns = [
            _concern(stage="plan_ensemble_risk_skeptic", severity="CRITICAL", idx=1),
        ]
        _state, prs = await _run_plan(config, 4343, concerns)

        prs.transition.assert_awaited_once_with(4343, "ready")
        prs.swap_pipeline_labels.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_adversarial_state_routes_to_ready(
        self, config: HydraFlowConfig
    ) -> None:
        """No accumulated concerns -> ready (guard is a no-op)."""
        phase, _state, planners, prs, store, _stop = make_plan_phase(config)
        issue = TaskFactory.create(id=4444)
        planners.plan = AsyncMock(
            return_value=PlanResultFactory.create(
                issue_number=4444,
                success=True,
                plan="The plan",
                summary="Done",
                use_defaults=True,
            )
        )
        store.get_plannable = supply_once([issue])

        await phase.plan_issues()

        prs.transition.assert_awaited_once_with(4444, "ready")
        prs.swap_pipeline_labels.assert_not_awaited()
