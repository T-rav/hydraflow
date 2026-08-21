"""Regression for #11482: epic re-plan must not steal #11464 ownership."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tests.conftest import PlanResultFactory, TaskFactory
from tests.helpers import make_plan_phase


@pytest.mark.asyncio
async def test_gap_replan_preserves_active_implement_owner(config) -> None:
    object.__setattr__(config, "epic_group_planning", True)
    phase, _state, planners, prs, store, _stop = make_plan_phase(config)
    children = [
        TaskFactory.create(
            id=issue_number,
            body="Parent Epic #11463\n\nImplement the planned child.",
            tags=["hydraflow-epic-child", "hydraflow-plan"],
            metadata={"epic_number": 11463},
        )
        for issue_number in (11464, 11465)
    ]
    for child in children:
        store.enqueue_transition(child, "plan")

    planners.plan = AsyncMock(
        side_effect=lambda task, **_kwargs: PlanResultFactory.create(
            issue_number=task.id,
            success=True,
            plan=f"Initial plan for #{task.id}",
            use_defaults=True,
        )
    )

    async def _request_stale_replan(*_args, **_kwargs) -> str:
        store.mark_active(11464, "implement")
        return (
            "GAP_REVIEW_START\n"
            "## Findings\nStale child snapshot.\n\n"
            "## Re-plan Required\n#11464\n\n"
            "## Guidance\nRe-plan the child.\n"
            "GAP_REVIEW_END\n"
        )

    planners.run_gap_review = AsyncMock(side_effect=_request_stale_replan)
    prs.get_issue_state = AsyncMock(return_value="OPEN")
    prs.get_issue_labels = AsyncMock(return_value=["hydraflow-plan"])

    await phase.plan_issues()

    # The store canonicalizes the phase name to its stage (#11551): the
    # implement owner is preserved and shows under READY.
    assert (
        planners.plan.await_count,
        store.get_active_issues(),
    ) == (2, {11464: "ready"})
