"""MockWorld scenario for the #11482 epic re-plan ownership guard.

The real ``PlanPhase.plan_issues`` runs against ``FakeIssueStore``,
``FakeGitHub``, and the scripted ``FakeLLM``. During the epic gap review an
implement worker owns #11464 while GitHub still presents a stale PLAN label.
The planner must leave both the worker claim and the second scripted plan
untouched.
"""

from __future__ import annotations

import pytest

from mockworld.fakes.fake_issue_store import FakeIssueStore
from plan_phase import PlanPhase

pytestmark = pytest.mark.scenario_loops


async def test_active_implement_child_is_not_replanned(mock_world) -> None:
    world = mock_world
    harness = world.harness
    object.__setattr__(harness.config, "epic_group_planning", True)
    for issue_number in (11464, 11465):
        world.add_issue(
            issue_number,
            f"Epic child #{issue_number}",
            "Parent Epic #11463\n\nImplement the planned child.",
            labels=["hydraflow-epic-child", "hydraflow-plan"],
        )

    world.set_phase_results(
        "plan",
        11464,
        [
            {"success": True, "plan": "Initial #11464 plan"},
            {"success": True, "plan": "FORBIDDEN second #11464 plan"},
        ],
    )
    world.set_phase_result(
        "plan",
        11465,
        {"success": True, "plan": "Initial #11465 plan"},
    )

    store = FakeIssueStore(github=world.github, event_bus=harness.bus)
    phase = PlanPhase(
        harness.config,
        harness.state,
        store,
        harness.planners,
        world.github,
        harness.bus,
        harness.stop_event,
    )

    async def _request_stale_replan(*_args, **_kwargs) -> str:
        claimed = store.get_implementable(1)
        if [task.id for task in claimed] != [11464]:
            raise AssertionError(f"expected #11464 implement claim, got {claimed!r}")
        store.mark_active(11464, "implement")
        await world.github.swap_pipeline_labels(11464, "hydraflow-plan")
        return (
            "GAP_REVIEW_START\n"
            "## Findings\nStale child snapshot.\n\n"
            "## Re-plan Required\n#11464\n\n"
            "## Guidance\nRe-plan the child.\n"
            "GAP_REVIEW_END\n"
        )

    harness.planners.run_gap_review = _request_stale_replan

    results = await phase.plan_issues()
    plans = {result.issue_number: result.plan for result in results}
    remaining_replans = world._llm.planners._scripts[11464]

    assert (
        plans[11464],
        len(remaining_replans),
        store.get_active_issues(),
    ) == ("Initial #11464 plan", 1, {11464: "implement"})
