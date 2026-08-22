"""LLMPort — the four runner surfaces used by the pipeline phases.

Kept structural — the parameter lists below mirror the REAL runner classes
(``triage.TriageRunner``, ``planner.PlannerRunner``, ``agent.AgentRunner``,
``reviewer.ReviewRunner``) verbatim, enforced by
``tests/test_mockworld_fakes_conformance.py::test_runner_ports_match_real_runner_signatures``.
Do NOT copy the FakeLLM stand-ins here — pairing a fake against a
fake-shaped Port is tautological and hides drift. When a production runner
signature changes, update this port in the same commit.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, runtime_checkable

from typing_extensions import Protocol


@runtime_checkable
class TriageRunnerPort(Protocol):
    async def evaluate(self, issue: Any, worker_id: int = 0) -> Any: ...


@runtime_checkable
class PlannerRunnerPort(Protocol):
    async def plan(
        self,
        task: Any,
        worker_id: int = 0,
        research_context: str = "",
        guidance: str = "",
        force_scale: Any | None = None,
    ) -> Any: ...
    async def run_gap_review(
        self,
        epic_number: int,
        child_plans: dict[Any, Any],
        child_titles: dict[Any, Any],
        *,
        issue_labels: Sequence[str] = (),
    ) -> str: ...


@runtime_checkable
class AgentRunnerPort(Protocol):
    async def run(
        self,
        task: Any,
        worktree_path: Path,
        branch: str,
        worker_id: int = 0,
        review_feedback: str = "",
        prior_failure: str = "",
        bead_mapping: dict[str, str] | None = None,
        human_guidance: str = "",
        attempt_number: int = 0,
        known_traps: str = "",
        timeout_s: int | None = None,
    ) -> Any: ...


@runtime_checkable
class ReviewRunnerPort(Protocol):
    async def review(
        self,
        pr: Any,
        issue: Any,
        worktree_path: Path,
        diff: str,
        worker_id: int = 0,
        code_scanning_alerts: list[Any] | None = None,
        bead_tasks: list[Any] | None = None,
        pre_flight_plan: Any | None = None,
        surface: str = "pr_review",
        human_guidance: str = "",
    ) -> Any: ...
    async def fix_ci(
        self,
        pr: Any,
        issue: Any,
        worktree_path: Path,
        failure_summary: str,
        attempt: int = 1,
        worker_id: int = 0,
        ci_logs: str = "",
        code_scanning_alerts: list[Any] | None = None,
    ) -> Any: ...
    async def fix_review_findings(
        self,
        pr: Any,
        issue: Any,
        worktree_path: Path,
        review_summary: str,
        worker_id: int = 0,
        advisor_transcript: str | None = None,
        suggested_fix_direction: str | None = None,
    ) -> Any: ...


@runtime_checkable
class LLMPort(Protocol):
    """Aggregate port exposing the four runners."""

    triage_runner: TriageRunnerPort
    planners: PlannerRunnerPort
    agents: AgentRunnerPort
    reviewers: ReviewRunnerPort
