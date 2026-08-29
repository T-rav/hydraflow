"""Regression pin for the 2026-08-16 light-tier HITL cascade (#11298).

Live failure: the #11304 light tier skipped the adversarial plan REVIEW
but not the plan ENSEMBLE. The ensemble critiqued deliberately-short lite
plans against full-scale expectations and raised >= 2 design-decision
CRITICAL concerns per issue; with no reviewer stage to resolve them, the
ready-swap design gate (`_route_to_hitl_if_design_decision`) routed every
light-tier issue to `human-required` — 9 issues in one morning, starving
the pipeline.

Pins:
1. A tier-eligible issue skips the ensemble (no ensemble spawn, no concerns
   raised into adversarial state).
2. A non-eligible issue still runs the ensemble (the #10659 protection is
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
    phase._ensemble_agents = [object()]  # wired, so only the tier gates
    phase._run_plan_ensemble = AsyncMock()
    return phase


def _state() -> dict:
    return {
        "issue": SimpleNamespace(id=1, tags=[]),
        "adv": SimpleNamespace(pending_concerns=[]),
        "result": SimpleNamespace(success=True, plan="Step 1: fix"),
    }


@pytest.mark.asyncio
async def test_light_tier_skips_ensemble() -> None:
    phase = _phase(HydraFlowConfig(), complexity=2)
    state = await phase._flow_ensemble(_state())
    phase._run_plan_ensemble.assert_not_awaited()
    assert state["result"].success is True


@pytest.mark.asyncio
async def test_full_tier_still_runs_ensemble() -> None:
    phase = _phase(HydraFlowConfig(), complexity=8)
    await phase._flow_ensemble(_state())
    phase._run_plan_ensemble.assert_awaited()


class TestThresholdTenSentinelCollapse:
    """#11314 (audit-upheld): at threshold=10, the old sentinel-10 for an
    UNCLASSIFIED issue collapsed into the skip path (10 > 10 is False),
    silently skipping the review for never-classified issues. Unknown
    complexity must be ineligible at EVERY threshold."""

    def _phase(self, config: HydraFlowConfig, *, record: object):
        phase = object.__new__(PlanPhase)
        phase._config = config
        phase._issue_cache = SimpleNamespace(latest_classification=lambda _id: record)
        phase._state = SimpleNamespace(get_route_back_count=lambda _id: 0)
        phase._has_escalation_label = lambda _issue: False
        return phase

    def test_unclassified_never_skips_even_at_threshold_ten(self) -> None:
        config = HydraFlowConfig(plan_review_min_complexity=10)
        phase = self._phase(config, record=None)
        skip, complexity = phase._skip_plan_review(SimpleNamespace(id=1))
        assert skip is False
        assert complexity == 10  # reported for logging only

    def test_honest_ten_skips_at_threshold_ten(self) -> None:
        """A genuinely-scored 10 at threshold 10 follows the config's plain
        meaning — only UNKNOWN is unconditionally ineligible."""
        config = HydraFlowConfig(plan_review_min_complexity=10)
        record = SimpleNamespace(payload={"complexity_score": 10})
        phase = self._phase(config, record=record)
        skip, _ = phase._skip_plan_review(SimpleNamespace(id=1))
        assert skip is True

    def test_none_payload_never_skips_at_threshold_ten(self) -> None:
        config = HydraFlowConfig(plan_review_min_complexity=10)
        record = SimpleNamespace(payload={"complexity_score": None})
        phase = self._phase(config, record=record)
        skip, _ = phase._skip_plan_review(SimpleNamespace(id=1))
        assert skip is False
