"""Tier-1 scenario: vetoes exhaust the blast-stratified retry budget → HITL.

T11 of the advisor-pattern feature, extended for refinement R-2. The
PostVerifyAdvisor retry budget is stratified by the diff's blast radius
(``BLAST_RADIUS_RETRIES`` = low:1, medium:2, high:3) rather than a flat
surface value, so the number of advisor calls before exhaustion scales
with risk:

- low blast  → 1 retry  → 2 calls then escalate
- medium     → 2 retries → 3 calls then escalate
- high blast → 3 retries → 4 calls then escalate

At *every* tier the safety invariant holds: once the budget is exhausted,
``ReviewPhase._run_post_verify_advisor`` routes the PR to HITL via
``_escalate_to_hitl`` (one ``HITL_ESCALATION`` event, cause
``advisor_post_verify_veto``) and the run does NOT merge. Blast radius is
driven by the seeded PR diff (``FakeGitHub.set_default_pr_diff``).
"""

from __future__ import annotations

import json

import pytest

from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario


def _veto_payload() -> str:
    """A blocking-severity VETO the advisor returns on every attempt."""
    return json.dumps(
        {
            "verdict": "VETO",
            "reasoning": "missed regression in module Y",
            "disagreements": [
                {
                    "executor_claim": "addressed",
                    "advisor_assessment": "still missing Y test",
                    "severity": "blocking",
                }
            ],
            "suggested_fix_direction": "add a regression test for Y",
        }
    )


def _blast_diff(tier: str) -> str:
    """Build a unified diff whose ``compute_blast_radius`` classifies as *tier*.

    ``low`` is the default stub (no src path), so callers just omit the seed.
    """
    if tier == "high":
        # src/orchestrator.py is a CRITICAL_PATHS_EXACT entry → blast=high.
        return (
            "diff --git a/src/orchestrator.py b/src/orchestrator.py\n"
            "+++ b/src/orchestrator.py\n"
            "+    _changed = True\n"
        )
    if tier == "medium":
        # >200 changed lines on a non-critical src file → blast=medium.
        body = "\n".join(f"+    field_{i} = {i}" for i in range(220))
        return (
            "diff --git a/src/feature_under_review.py "
            "b/src/feature_under_review.py\n"
            "+++ b/src/feature_under_review.py\n"
            f"{body}\n"
        )
    raise ValueError(f"unsupported tier: {tier}")


def _veto_escalations(result, issue_number: int) -> list:
    """The advisor-post-verify-veto HITL escalation events for *issue_number*.

    Asserting on the event (not label state) is durable across post-escalation
    phases: after the exhaustion branch flips the verdict to REQUEST_CHANGES,
    the caller's normal REQUEST_CHANGES handling re-queues to ready and would
    otherwise overwrite a diagnose label.
    """
    events = result.pipeline_results[0].events
    return [
        e
        for e in events
        if e.type.value == "hitl_escalation"
        and e.data.get("cause") == "advisor_post_verify_veto"
        and e.data.get("issue") == issue_number
    ]


class TestPRReviewVetoExhaustedEscalatesHITL:
    """Blast-stratified budget exhaustion routes to HITL with no merge."""

    @staticmethod
    def _enable_advisor(monkeypatch) -> None:
        # Enable the advisor master + pr_review surface kill-switches explicitly
        # so the retry loop is reachable regardless of test-suite defaults.
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_POSTVERIFY_ENABLED", "true")

    async def test_medium_blast_escalates_after_three_calls(
        self, mock_world, monkeypatch
    ) -> None:
        """Medium blast → budget 2 → initial + 2 retries = 3 calls → HITL."""
        self._enable_advisor(monkeypatch)
        world = mock_world
        IssueBuilder().numbered(13).titled("Stuck change").bodied(
            "Persistently disputed by advisor"
        ).at(world)
        world.github.set_default_pr_diff(_blast_diff("medium"))
        world._llm.script_advisor(13, "post_verify", [_veto_payload()] * 3)

        result = await world.run_pipeline()

        outcome = result.issue(13)
        assert outcome.review_result is not None
        assert outcome.merged is False, "PR must not merge after veto exhaustion"
        assert world._llm.advisor_call_count_for("post_verify") == 3, (
            "medium blast: advisor fires 3 times (initial + 2 retries) then escalates"
        )
        assert len(_veto_escalations(result, 13)) == 1

    async def test_low_blast_escalates_after_two_calls(
        self, mock_world, monkeypatch
    ) -> None:
        """Low blast (default stub diff) → budget 1 → 2 calls → HITL sooner."""
        self._enable_advisor(monkeypatch)
        world = mock_world
        IssueBuilder().numbered(14).titled("Trivial dispute").bodied(
            "Small change the advisor keeps vetoing"
        ).at(world)
        # No diff seed → default stub has no src path → blast=low → budget 1.
        world._llm.script_advisor(14, "post_verify", [_veto_payload()] * 2)

        result = await world.run_pipeline()

        outcome = result.issue(14)
        assert outcome.merged is False, "PR must not merge after veto exhaustion"
        assert world._llm.advisor_call_count_for("post_verify") == 2, (
            "low blast: advisor fires 2 times (initial + 1 retry) then escalates"
        )
        assert len(_veto_escalations(result, 14)) == 1

    async def test_high_blast_escalates_after_four_calls(
        self, mock_world, monkeypatch
    ) -> None:
        """High blast (critical path) → budget 3 → 4 calls before HITL."""
        self._enable_advisor(monkeypatch)
        world = mock_world
        IssueBuilder().numbered(15).titled("Risky core change").bodied(
            "Critical-path change the advisor keeps vetoing"
        ).at(world)
        world.github.set_default_pr_diff(_blast_diff("high"))
        world._llm.script_advisor(15, "post_verify", [_veto_payload()] * 4)

        result = await world.run_pipeline()

        outcome = result.issue(15)
        assert outcome.merged is False, "PR must not merge after veto exhaustion"
        assert world._llm.advisor_call_count_for("post_verify") == 4, (
            "high blast: advisor fires 4 times (initial + 3 retries) then escalates"
        )
        assert len(_veto_escalations(result, 15)) == 1
