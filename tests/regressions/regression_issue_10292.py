"""Regression guard for #10292 — memory-backlog shape-fork must not pile into HITL.

`MemoryBacklogLoop` (ADR-0089) files `hydraflow-find` issues to build enforcement
for captured memories. A BEHAVIORAL memory (e.g. `feedback_backlog_to_loop_
reflection`) has no single enforcement direction, so the ADR-0107 planner shape
gate forked #10292 into 4 divergent platform directions, escalated a P4 to HITL,
and it churned the diagnose loop — a HITL pile-up for something the captured
memory already covers.

Fix: when the shape gate can't finalize a direction AND the issue is a
memory-backlog issue, resolve it as CAPTURED (closed) with a re-file path,
instead of escalating to HITL. Non-memory-backlog forks still escalate.

This guard pins both arms: a memory-backlog fork closes (not HITL); a normal
issue's fork still escalates.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from models import DiscoverResult, ShapeTurnResult
from tests.conftest import TaskFactory
from tests.helpers import make_plan_phase, supply_once


def _wire_shape_fork(phase):
    """Arm discovery (2 opportunities) + a non-final shape turn -> a fork."""
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
async def test_memory_backlog_shape_fork_closes_not_hitl(config) -> None:
    phase, _state, planners, prs, store, _stop = make_plan_phase(config)
    _wire_shape_fork(phase)
    issue = TaskFactory.create(id=1, tags=[config.memory_backlog_label[0]])
    store.get_plannable = supply_once([issue])

    results = await phase.plan_issues()

    prs.close_task.assert_awaited_once_with(1)
    assert any(r.error == "memory_backlog_shape_captured" for r in results)
    assert not any(r.error == "shape_escalated" for r in results)
    planners.plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_memory_backlog_shape_fork_still_escalates(config) -> None:
    phase, _state, planners, prs, store, _stop = make_plan_phase(config)
    _wire_shape_fork(phase)
    issue = TaskFactory.create(id=1)  # no memory-backlog label
    store.get_plannable = supply_once([issue])

    results = await phase.plan_issues()

    prs.close_task.assert_not_awaited()
    assert any(r.error == "shape_escalated" for r in results)
