"""Regression pin for the 2026-08-16 light-tier HITL cascade (#11298).

Live failure: the #11304 light tier skipped the adversarial plan REVIEW
but not the plan COUNCIL. The council critiqued deliberately-short lite
plans against full-scale expectations and raised >= 2 design-decision
CRITICAL concerns per issue; with no reviewer stage to resolve them, the
ready-swap design gate (`_route_to_hitl_if_design_decision`) routed every
light-tier issue to `human-required` — 9 issues in one morning, starving
the pipeline.

Pins:
1. A tier-eligible issue skips the council (no council spawn, no concerns
   raised into adversarial state).
2. A non-eligible issue still runs the council (the #10659 protection is
   untouched for full-tier work).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config import HydraFlowConfig
from plan_phase import PlanPhase


def _phase(config: HydraFlowConfig, *, complexity: int):
    phase = object.__new__(PlanPhase)
    phase._config = config
    phase._issue_cache = SimpleNamespace(
        latest_classification=lambda _id: SimpleNamespace(
            payload={"complexity_score": complexity}
        )
    )
    phase._state = SimpleNamespace(get_route_back_count=lambda _id: 0)
    phase._has_escalation_label = lambda _issue: False
    phase._council_agents = [object()]  # wired, so only the tier gates
    phase._run_plan_council = AsyncMock()
    return phase


def _state() -> dict:
    return {
        "issue": SimpleNamespace(id=1, tags=[]),
        "adv": SimpleNamespace(pending_concerns=[]),
        "result": SimpleNamespace(success=True, plan="Step 1: fix"),
    }


@pytest.mark.asyncio
async def test_light_tier_skips_council() -> None:
    phase = _phase(HydraFlowConfig(), complexity=2)
    state = await phase._flow_council(_state())
    phase._run_plan_council.assert_not_awaited()
    assert state["result"].success is True


@pytest.mark.asyncio
async def test_full_tier_still_runs_council() -> None:
    phase = _phase(HydraFlowConfig(), complexity=8)
    await phase._flow_council(_state())
    phase._run_plan_council.assert_awaited()
