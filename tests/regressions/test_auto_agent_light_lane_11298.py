"""Regression pins for the #11298 auto-agent light lane.

The lane routes triage-scored simple issues to the single-session
auto-agent (one spawn: read issue → implement → test → PR) instead of the
staged plan/review pipeline — the 'Claude session with a goal' mode.

Pins:
1. Default OFF — zero behavior change until the operator flips
   auto_agent_light_intake_enabled.
2. Routing swaps to the claim label and stops the plan flow BEFORE any
   planner/research spawn; the shared _tier_eligible guard applies
   (cycled/escalated/unscored never route).
3. Exhaustion falls back to the staged pipeline (planner label +
   route-back increment) — NEVER to a human. The route-back also
   disqualifies the issue from every tier gate on the next pass.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config import HydraFlowConfig
from plan_phase import PlanPhase


def test_light_lane_defaults_off() -> None:
    config = HydraFlowConfig()
    assert config.auto_agent_light_intake_enabled is False
    assert config.auto_agent_light_max_complexity == 3
    assert config.light_autofix_label == ["hydraflow-auto-light"]


def _phase(config: HydraFlowConfig, *, complexity, route_backs: int = 0):
    phase = object.__new__(PlanPhase)
    phase._config = config
    record = (
        SimpleNamespace(payload={"complexity_score": complexity})
        if complexity is not None
        else None
    )
    phase._issue_cache = SimpleNamespace(latest_classification=lambda _id: record)
    phase._state = SimpleNamespace(
        get_route_back_count=lambda _id: route_backs,
        get_human_steering=lambda _id: SimpleNamespace(guidance=""),
    )
    phase._has_escalation_label = lambda _issue: False
    phase._prs = SimpleNamespace(swap_pipeline_labels=AsyncMock())
    phase._research_runner = None
    phase._should_research = lambda _issue: False
    return phase


def _state_for(issue_id: int = 42) -> dict:
    return {"issue": SimpleNamespace(id=issue_id, tags=[])}


@pytest.mark.asyncio
async def test_eligible_issue_routes_to_light_lane() -> None:
    config = HydraFlowConfig(auto_agent_light_intake_enabled=True)
    phase = _phase(config, complexity=2)
    state = await phase._flow_prepass(_state_for())
    phase._prs.swap_pipeline_labels.assert_awaited_once_with(42, "hydraflow-auto-light")
    assert state["_stop"] is True
    assert "light-lane" in state["result"].summary


@pytest.mark.asyncio
async def test_flag_off_never_routes() -> None:
    config = HydraFlowConfig(auto_agent_light_intake_enabled=False)
    phase = _phase(config, complexity=1)
    state = _state_for()
    routed = await phase._route_light_lane(state["issue"], state)
    assert routed is False
    phase._prs.swap_pipeline_labels.assert_not_awaited()


@pytest.mark.asyncio
async def test_above_threshold_stays_in_pipeline() -> None:
    config = HydraFlowConfig(auto_agent_light_intake_enabled=True)
    phase = _phase(config, complexity=4)  # above the 3 default, within plan tier
    state = _state_for()
    assert await phase._route_light_lane(state["issue"], state) is False
    phase._prs.swap_pipeline_labels.assert_not_awaited()


@pytest.mark.asyncio
async def test_cycled_issue_never_routes() -> None:
    config = HydraFlowConfig(auto_agent_light_intake_enabled=True)
    phase = _phase(config, complexity=1, route_backs=1)
    state = _state_for()
    assert await phase._route_light_lane(state["issue"], state) is False
    phase._prs.swap_pipeline_labels.assert_not_awaited()


@pytest.mark.asyncio
async def test_unscored_issue_never_routes() -> None:
    config = HydraFlowConfig(auto_agent_light_intake_enabled=True)
    phase = _phase(config, complexity=None)
    state = _state_for()
    assert await phase._route_light_lane(state["issue"], state) is False
    phase._prs.swap_pipeline_labels.assert_not_awaited()
