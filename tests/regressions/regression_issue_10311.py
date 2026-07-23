"""Regression guard for #10311 — unprioritized shape forks defer, not HITL.

Generalizes the #10292 fix: the ADR-0107 planner shape gate escalates a fork to
HITL for ANY issue with >=2 discovery opportunities, with no notion of whether a
human choice is actually warranted. A P4/housekeeping fork (an unrefined or
self-filed issue with no priority) just piles up the HITL queue.

Fix: a shape fork escalates to HITL ONLY when the issue carries a P0/P1/P2
priority label (a genuine, prioritized human-direction choice). An unprioritized
fork DEFERS (closed with a re-engage path — set a priority or re-file with a
direction) instead. HITL is for prioritized choices, not low-value forks.

Pins both arms: unprioritized -> deferred; prioritized -> escalated.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from models import DiscoverResult, ShapeTurnResult
from tests.conftest import TaskFactory
from tests.helpers import make_plan_phase, supply_once


def _wire_shape_fork(phase):
    record = MagicMock()
    record.payload = {"clarity_score": 2, "needs_discovery": True}
    cache = MagicMock()
    cache.latest_classification.return_value = record
    phase._issue_cache = cache
    discover = AsyncMock()
    discover.discover = AsyncMock(
        return_value=DiscoverResult(
            issue_number=1, research_brief="brief", opportunities=["A", "B"]
        )
    )
    phase._discover_runner = discover
    shape = AsyncMock()
    shape.run_turn = AsyncMock(
        return_value=ShapeTurnResult(content="A vs B", is_final=False)
    )
    phase._shape_runner = shape


@pytest.mark.asyncio
async def test_unprioritized_shape_fork_defers_not_hitl(config) -> None:
    phase, _s, planners, prs, store, _stop = make_plan_phase(config)
    _wire_shape_fork(phase)
    issue = TaskFactory.create(id=1)  # no P0/P1/P2 priority
    store.get_plannable = supply_once([issue])

    results = await phase.plan_issues()

    prs.close_task.assert_awaited_once_with(1)  # deferred (closed), not HITL
    assert any(r.error == "shape_deferred_unprioritized" for r in results)
    assert not any(r.error == "shape_escalated" for r in results)
    planners.plan.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("prio", ["P0", "P1", "P2"])
async def test_prioritized_shape_fork_still_escalates(config, prio) -> None:
    phase, _s, planners, prs, store, _stop = make_plan_phase(config)
    _wire_shape_fork(phase)
    issue = TaskFactory.create(id=1, tags=[prio])
    store.get_plannable = supply_once([issue])

    results = await phase.plan_issues()

    assert any(r.error == "shape_escalated" for r in results)
    assert not any(r.error == "shape_deferred_unprioritized" for r in results)
    prs.close_task.assert_not_awaited()
