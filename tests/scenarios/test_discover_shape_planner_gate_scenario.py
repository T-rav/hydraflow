"""MockWorld scenario for the ADR-0107 planner-invoked discover helper.

Collapse-Discover-Shape step 1 (#9773): with ``collapse_discover_shape`` on,
Triage routes a ready issue straight to Plan regardless of clarity — no
``hydraflow-discover`` hop. The clarity/needs-discovery signals ride along as
HINTS on the shared ``IssueCache`` classification record (mirroring
``service_registry.py``'s production wiring, where Triage and Plan share one
``IssueCache`` instance). The planner's decision gate
(``plan_phase.py:_should_discover_helper``) reads those hints back and, for a
low-clarity issue, invokes the ``DiscoverRunner``-backed helper before
planning — and the issue still reaches a successful plan afterward.

Scenario 2 covers the conservative default: a well-specified (high-clarity)
issue plans directly with no helper invocation, exactly like the flag-off
path — proving the gate doesn't fire indiscriminately just because the flag
is on.
"""

from __future__ import annotations

from typing import Any

import pytest

from models import DiscoverResult, Task

pytestmark = pytest.mark.scenario


class _ScriptedDiscoverRunner:
    """Records calls and returns a scripted ``DiscoverResult``.

    Stands in for the real subprocess-backed ``DiscoverRunner`` the same way
    ``test_plan_touchpoint_expander_scenario.py``'s ``_ScriptedReviewer`` /
    ``_ScriptedExpander`` stand in for their real engines — the planner-gate
    wiring under test doesn't care which concrete engine it invokes.
    """

    def __init__(self, result: DiscoverResult) -> None:
        self._result = result
        self.calls: list[Task] = []

    async def discover(self, task: Task, *, guidance: str = "") -> DiscoverResult:
        self.calls.append(task)
        return self._result


def _wire_shared_issue_cache(harness: Any, tmp_path: Any) -> Any:
    """Wire a real ``IssueCache`` shared by TriagePhase + PlanPhase.

    Mirrors ``service_registry.py``'s production wiring, where a single
    ``IssueCache`` instance is passed to both phases — Triage's
    ``record_classification`` call is how the ADR-0107 clarity/needs-
    discovery hints reach the planner's decision gate
    (``plan_phase.py:_triage_hints`` reads them back via
    ``latest_classification``). The harness's default ``PipelineHarness``
    wiring leaves both phases' ``_issue_cache`` at ``None``.
    """
    from issue_cache import IssueCache

    cache = IssueCache(tmp_path / "issue_cache")
    harness.triage_phase._issue_cache = cache
    harness.plan_phase._issue_cache = cache
    return cache


class TestS1LowClarityIssueGetsDiscoverHelper:
    """Flag ON: a low-clarity ready issue routes Triage -> Plan directly,
    the planner's gate invokes the discover helper before planning, and the
    issue still reaches a successful plan."""

    async def test_low_clarity_issue_discovers_then_plans(
        self, mock_world, tmp_path
    ) -> None:
        world = mock_world
        harness = world.harness
        harness.config.collapse_discover_shape = True
        _wire_shared_issue_cache(harness, tmp_path)

        discover_runner = _ScriptedDiscoverRunner(
            DiscoverResult(
                issue_number=401,
                research_brief=(
                    "Competitive landscape: three adjacent tools, one clear gap."
                ),
                opportunities=["Ship a focused MVP targeting the gap"],
            )
        )
        harness.plan_phase._discover_runner = discover_runner

        world.add_issue(
            401,
            "Improve onboarding experience",
            "Users drop off during signup. " * 5,
            labels=["hydraflow-find"],
        )
        world._llm.script_triage(
            401,
            [{"ready": True, "clarity_score": 3, "needs_discovery": False}],
        )
        world._llm.script_plan(
            401,
            [{"success": True, "plan": "## Plan\n\n1. Redesign signup flow"}],
        )

        result = await world.run_pipeline()

        # Triage routed straight to Plan — no hydraflow-discover hop, per
        # the keystone's flag-gated routing (triage_phase.py).
        outcome = result.issue(401)
        assert "hydraflow-discover" not in outcome.labels

        # The planner's decision gate invoked the discover helper before
        # planning, reading the low-clarity hint back off the shared cache.
        assert len(discover_runner.calls) == 1
        assert discover_runner.calls[0].id == 401

        # Planning still completed successfully — discovery didn't block it.
        assert outcome.plan_result is not None
        assert outcome.plan_result.success is True
        assert outcome.final_stage != "triage"


class TestS2WellSpecifiedIssueSkipsHelper:
    """Flag ON, conservative default: a well-specified (high-clarity) issue
    plans directly with no helper invocation."""

    async def test_high_clarity_issue_plans_without_discover_helper(
        self, mock_world, tmp_path
    ) -> None:
        world = mock_world
        harness = world.harness
        harness.config.collapse_discover_shape = True
        _wire_shared_issue_cache(harness, tmp_path)

        discover_runner = _ScriptedDiscoverRunner(
            DiscoverResult(issue_number=402, research_brief="should not be reached")
        )
        harness.plan_phase._discover_runner = discover_runner

        world.add_issue(
            402,
            "Add pagination to the users endpoint",
            "Add limit/offset query params to GET /users. " * 3,
            labels=["hydraflow-find"],
        )
        world._llm.script_triage(
            402,
            [{"ready": True, "clarity_score": 9, "needs_discovery": False}],
        )
        world._llm.script_plan(
            402,
            [{"success": True, "plan": "## Plan\n\n1. Add pagination params"}],
        )

        result = await world.run_pipeline()

        outcome = result.issue(402)
        assert "hydraflow-discover" not in outcome.labels
        assert discover_runner.calls == []
        assert outcome.plan_result is not None
        assert outcome.plan_result.success is True
        assert outcome.final_stage != "triage"
