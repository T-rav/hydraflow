"""Edge case scenario tests — race conditions, mid-flight mutations."""

from __future__ import annotations

import pytest

from tests.conftest import WorkerResultFactory

pytestmark = pytest.mark.scenario


class TestE1DuplicateIssues:
    """E1: Duplicate issues — pipeline must not crash and must track each by number."""

    async def test_same_title_body_both_tracked_by_number(self, mock_world):
        """Two issues with identical title+body are seeded independently.

        Discovered behavior: ``FakeGitHub.find_existing_issue`` resolves by
        title, so when two open issues share a title only the first one
        observed wins the dedup lookup. The pipeline still produces an
        ``IssueOutcome`` for each issue number — duplicates do not crash the
        pipeline and each is independently inspectable. Production-style
        dedup is the responsibility of the upstream issue-creation path,
        not the in-pipeline phases. If a future change makes the pipeline
        actively dedup duplicates this test should be updated to assert the
        new contract.
        """
        world = mock_world.add_issue(
            1, "Fix auth bug", "The auth module is broken"
        ).add_issue(2, "Fix auth bug", "The auth module is broken")
        result = await world.run_pipeline()

        # Both issues are tracked independently by number
        assert result.issue(1).number == 1
        assert result.issue(2).number == 2
        # At least one of them must reach a real terminal stage; the other
        # is allowed to lag because of upstream title-based dedup.
        stages = {result.issue(1).final_stage, result.issue(2).final_stage}
        assert "done" in stages or "review" in stages, (
            f"Expected at least one duplicate to progress past triage; got {stages}"
        )


class TestE2IssueRelabeledMidFlight:
    """E2: on_phase hook fires before a phase runs."""

    async def test_on_phase_hook_fires(self, mock_world):
        fired = {"count": 0}

        def hook():
            fired["count"] += 1

        world = mock_world.add_issue(1, "Refactor DB", "Needs DB refactor").on_phase(
            "plan", hook
        )
        result = await world.run_pipeline()

        assert fired["count"] == 1, "on_phase hook should fire exactly once"
        # Pipeline still processes the issue normally
        assert result.issue(1) is not None


class TestE5ZeroDiffImplement:
    """E5: Agent produces zero commits — already-satisfied case."""

    async def test_zero_commits_worker_result(self, mock_world):
        zero_diff = WorkerResultFactory.create(
            issue_number=1,
            success=True,
            commits=0,
        )
        world = mock_world.add_issue(
            1, "Add type hints", "Already typed module"
        ).set_phase_result("implement", 1, zero_diff)
        result = await world.run_pipeline()

        outcome = result.issue(1)
        assert outcome.worker_result is not None
        assert outcome.worker_result.commits == 0
        assert outcome.worker_result.success is True
