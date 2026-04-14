"""LLMPort — the four runner surfaces used by the pipeline phases.

Kept structural — matches the method signatures the phases actually call.
When production runner signatures drift, update this port.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, runtime_checkable

from typing_extensions import Protocol


@runtime_checkable
class TriageRunnerPort(Protocol):
    async def evaluate(self, issue: Any, worker_id: int = 0) -> Any: ...
    async def run_decomposition(self, task: Any) -> Any: ...


@runtime_checkable
class PlannerRunnerPort(Protocol):
    async def plan(
        self,
        task: Any,
        *,
        worker_id: int = 0,
        research_context: str = "",
        **_: Any,
    ) -> Any: ...
    async def run_gap_review(
        self,
        epic_number: int,
        child_plans: dict[Any, Any],
        child_titles: dict[Any, Any],
    ) -> str: ...


@runtime_checkable
class AgentRunnerPort(Protocol):
    async def run(
        self,
        task: Any,
        worktree_path: Path,
        branch: str,
        *,
        worker_id: int = 0,
        review_feedback: str = "",
        prior_failure: str = "",
        bead_mapping: dict[str, str] | None = None,
        **_: Any,
    ) -> Any: ...


@runtime_checkable
class ReviewRunnerPort(Protocol):
    async def review(
        self,
        pr: Any,
        issue: Any,
        worktree_path: Path,
        diff: str,
        *,
        worker_id: int = 0,
        code_scanning_alerts: list[Any] | None = None,
        bead_tasks: list[Any] | None = None,
        **_: Any,
    ) -> Any: ...
    async def fix_ci(
        self,
        pr: Any,
        issue: Any,
        worktree_path: Path,
        failure_summary: str,
        **_: Any,
    ) -> Any: ...


@runtime_checkable
class LLMPort(Protocol):
    """Aggregate port exposing the four runners."""

    triage_runner: TriageRunnerPort
    planners: PlannerRunnerPort
    agents: AgentRunnerPort
    reviewers: ReviewRunnerPort
