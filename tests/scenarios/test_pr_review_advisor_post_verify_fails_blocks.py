"""Tier-1 scenario: HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO=true →
when advisor errors, treat as VETO instead of degrading.

T15 of the advisor-pattern feature. Validates the fail-closed mode of
the advisor failure-mode envelope: each advisor invocation hits a
parse-error path (no scripted result), ``_handle_failure`` returns VETO
(because FAIL_AS_VETO=true), and the bounded retry loop exhausts —
escalating to HITL with the merge blocked. The PR is seeded with a
medium-blast diff so the R-2 blast-stratified budget is 2 (medium tier),
i.e. initial + 2 retries = 3 calls before exhaustion.
"""

from __future__ import annotations

import pytest

from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario


class TestPRReviewAdvisorPostVerifyFailsBlocks:
    """Runner-error treated as VETO under FAIL_AS_VETO — exhausts to HITL."""

    async def test_runner_error_blocks_with_fail_as_veto(
        self, mock_world, monkeypatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO", "true")

        world = mock_world
        IssueBuilder().numbered(24).titled("docs").bodied("docs").at(world)
        # Seed a medium-blast diff (>200 changed lines on a non-critical src
        # file → blast=medium → budget 2) so the assertion below is exactly
        # initial + 2 retries = 3 calls before exhaustion.
        medium_diff = "+++ b/src/feature.py\n" + "\n".join(
            f"+    field_{i} = {i}" for i in range(220)
        )
        world.github.set_default_pr_diff(medium_diff)

        # No advisor result scripted → JSON parse error on each retry attempt
        # → all attempts return VETO under FAIL_AS_VETO=true →
        # exhausted → HITL escalation, no merge

        result = await world.run_pipeline()
        outcome = result.issue(24)
        # Medium-blast budget+1 = 3 advisor invocations before exhaustion.
        assert world._llm.advisor_call_count_for("post_verify") == 3
        assert outcome.merged is False
