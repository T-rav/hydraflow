"""A failed escalation must not move the issue's stage anyway.

#6536's unit pin asserts `enqueue_transition` was not called. This asserts the
thing that matters downstream: the issue's actual labels in FakeGitHub.

`FakeIssueStore.enqueue_transition` applies the stage by mutating those
labels, so an unconditional call did not merely record an intention — it put
the issue into `diagnose` while nothing had escalated it. Every later reader
(the loops that route by label, the board, an operator) then sees a stage the
pipeline never reached, and the issue is invisible to whatever would
otherwise retry the escalation.

The successful-escalation test is the decoy: without it, "the label did not
move" would be satisfied just as well by an escalator that had stopped
transitioning anything.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from harness_insights import FailureCategory
from models import PipelineStage
from phase_utils import PipelineEscalator
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops

_ISSUE = 4242
_PLAN = "hydraflow-planning"
_DIAGNOSE = "hydraflow-diagnose"
_HITL = "hydraflow-hitl"


def _build(world: MockWorld, prs) -> PipelineEscalator:
    from mockworld.fakes.fake_issue_store import FakeIssueStore  # noqa: PLC0415

    store = FakeIssueStore(world._github, world._harness.bus)
    return PipelineEscalator(
        world._harness.state,
        prs,
        store,
        MagicMock(),
        origin_label=_PLAN,
        hitl_label=_HITL,
        diagnose_label=_DIAGNOSE,
        stage=PipelineStage.PLAN,
    )


def _labels(world: MockWorld) -> list[str]:
    return list(world._github._issues[_ISSUE].labels)


async def test_both_paths_failing_leaves_the_stage_untouched(tmp_path) -> None:
    world = MockWorld(tmp_path)
    world.add_issue(_ISSUE, "t", "b", labels=[_PLAN])

    prs = AsyncMock()
    prs.swap_pipeline_labels.side_effect = RuntimeError("swap failed")
    escalator = _build(world, prs)

    with patch(
        "phase_utils.escalate_to_diagnostic",
        new_callable=AsyncMock,
        side_effect=RuntimeError("escalation failed"),
    ):
        await escalator(
            MagicMock(id=_ISSUE),
            cause="plan failed",
            details="validation errors",
            category=FailureCategory.PLAN_VALIDATION,
        )

    labels = _labels(world)
    assert _DIAGNOSE not in labels, (
        "the issue was moved to diagnose even though the escalation AND its "
        f"fallback both failed — nothing put it there. Labels: {labels}"
    )
    assert _PLAN in labels, (
        f"the issue should still be in its original stage. Labels: {labels}"
    )


async def test_a_successful_escalation_still_moves_the_stage(tmp_path) -> None:
    """The decoy: the transition must still happen on the happy path."""
    world = MockWorld(tmp_path)
    world.add_issue(_ISSUE, "t", "b", labels=[_PLAN])

    escalator = _build(world, AsyncMock())

    with patch("phase_utils.escalate_to_diagnostic", new_callable=AsyncMock):
        await escalator(
            MagicMock(id=_ISSUE),
            cause="plan failed",
            details="validation errors",
            category=FailureCategory.PLAN_VALIDATION,
        )

    labels = _labels(world)
    assert _DIAGNOSE in labels, (
        "a successful escalation must still record the transition — without "
        f"this, the assertion above is satisfied by doing nothing. Labels: {labels}"
    )
