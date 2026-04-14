"""Happy path scenario tests — prove the golden path works."""

from __future__ import annotations

import pytest

from tests.conftest import PlanResultFactory
from tests.scenarios.builders import IssueBuilder, RepoStateBuilder

pytestmark = pytest.mark.scenario


class TestH1SingleIssueEndToEnd:
    """H1: Single issue flows find → triage → plan → implement → review → done."""

    async def test_single_issue_lifecycle(self, mock_world):
        world = mock_world
        IssueBuilder().numbered(1).titled("Add login button").bodied(
            "Add a login button to the homepage"
        ).at(world)
        result = await world.run_pipeline()

        outcome = result.issue(1)
        assert outcome.final_stage == "done"
        assert outcome.merged is True
        assert outcome.plan_result is not None
        assert outcome.plan_result.success is True
        assert outcome.worker_result is not None
        assert outcome.worker_result.success is True


class TestH2MultiIssueConcurrentBatch:
    """H2: Multiple issues processed without cross-contamination."""

    async def test_three_issues_all_complete(self, mock_world):
        world = mock_world
        await (
            RepoStateBuilder()
            .with_issues(
                [
                    IssueBuilder()
                    .numbered(1)
                    .titled("Bug fix A")
                    .bodied("Fix the A module"),
                    IssueBuilder()
                    .numbered(2)
                    .titled("Bug fix B")
                    .bodied("Fix the B module"),
                    IssueBuilder()
                    .numbered(3)
                    .titled("Bug fix C")
                    .bodied("Fix the C module"),
                ]
            )
            .at(world)
        )
        result = await world.run_pipeline()

        for num in (1, 2, 3):
            outcome = result.issue(num)
            assert outcome.final_stage == "done", f"Issue {num} did not complete"
            assert outcome.merged is True, f"Issue {num} PR not merged"

    async def test_no_cross_contamination(self, mock_world):
        world = mock_world
        await (
            RepoStateBuilder()
            .with_issues(
                [
                    IssueBuilder().numbered(10).titled("Feature X").bodied("Build X"),
                    IssueBuilder().numbered(20).titled("Feature Y").bodied("Build Y"),
                ]
            )
            .at(world)
        )
        result = await world.run_pipeline()

        assert result.issue(10).worker_result is not None
        assert result.issue(10).worker_result.issue_number == 10
        assert result.issue(20).worker_result is not None
        assert result.issue(20).worker_result.issue_number == 20


class TestH4ReviewApproveAndMerge:
    """H4: Review returns APPROVE, CI passes, PR merged."""

    async def test_approve_merge_flow(self, mock_world):
        world = mock_world
        IssueBuilder().numbered(1).titled("Small refactor").bodied(
            "Clean up utils module"
        ).at(world)
        result = await world.run_pipeline()

        outcome = result.issue(1)
        assert outcome.review_result is not None
        assert outcome.merged is True
        pr = world.github.pr_for_issue(1)
        assert pr is not None
        assert pr.merged is True


class TestH5PlanProducesSubIssues:
    """H5: Planner returns new_issues, sub-issues tracked in plan result."""

    async def test_sub_issues_in_plan_result(self, mock_world):
        from models import NewIssueSpec

        plan_with_subs = PlanResultFactory.create(
            issue_number=1,
            success=True,
            new_issues=[
                NewIssueSpec(title="Sub-task 1", body="Do sub-task 1"),
                NewIssueSpec(title="Sub-task 2", body="Do sub-task 2"),
            ],
        )
        world = mock_world
        IssueBuilder().numbered(1).titled("Epic task").bodied("Big feature").at(world)
        world.set_phase_result("plan", 1, plan_with_subs)
        result = await world.run_pipeline()

        outcome = result.issue(1)
        assert outcome.plan_result is not None
        assert outcome.plan_result.new_issues is not None
        assert len(outcome.plan_result.new_issues) == 2


class TestH3HITLRoundTrip:
    """H3: Failed implement routes issue to HITL-like state (does not complete)."""

    async def test_implement_failure_routes_to_hitl(self, mock_world):
        """When implement fails, the issue should not reach 'done' —
        it stops at implement stage, representing an HITL escalation point.
        """
        from tests.conftest import WorkerResultFactory

        fail = WorkerResultFactory.create(
            issue_number=1, success=False, error="Docker build failed"
        )
        world = mock_world.add_issue(
            1, "Complex refactor", "Needs careful human review"
        ).set_phase_result("implement", 1, fail)
        result = await world.run_pipeline()

        outcome = result.issue(1)
        assert outcome.final_stage != "done", (
            "Failed implement should not reach done — should be escalation point"
        )
        assert outcome.worker_result is not None
        assert outcome.worker_result.success is False
        assert outcome.merged is False
