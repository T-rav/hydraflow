"""Result types for scenario tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tests.helpers import PipelineRunResult


@dataclass
class IssueOutcome:
    """Per-issue outcome view after a scenario run."""

    number: int
    final_stage: str
    attempt_count: int = 0
    triage_count: int = 0
    plan_result: Any = None
    worker_result: Any = None
    review_result: Any = None
    hitl_result: Any = None
    labels: list[str] = field(default_factory=list)
    merged: bool = False


@dataclass
class ScenarioResult:
    """Outcome of a scenario run — wraps PipelineRunResult(s)."""

    pipeline_results: list[PipelineRunResult]
    loop_stats: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    duration_seconds: float = 0.0
    _outcomes: dict[int, IssueOutcome] = field(default_factory=dict)
    _config_snapshots: dict[str, Any] = field(default_factory=dict)

    def issue(self, number: int) -> IssueOutcome:
        if number not in self._outcomes:
            msg = f"No outcome for issue {number}; available: {list(self._outcomes)}"
            raise KeyError(msg)
        return self._outcomes[number]

    def config_snapshot(self, key: str) -> Any:
        return self._config_snapshots.get(key)
