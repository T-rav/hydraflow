"""Per-loop fitness contract and pure scoring helpers (read-only).

Substrate for the deferred hill-climb optimizer: every fitness function is
pure over a ``FitnessContext`` (a data-only model with no live client), so the
same function scores live history now and replayed history later. See
``docs/superpowers/specs/2026-06-30-loop-fitness-scorecard-design.md``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class FitnessKind(StrEnum):
    """Whether a loop emits a normalized score or only raw counters."""

    SCORED = "scored"
    HOUSEKEEPING = "housekeeping"


class Confidence(StrEnum):
    """Whether the sample size supports a trustworthy score."""

    OK = "ok"
    INSUFFICIENT_DATA = "insufficient_data"


class IssueRecord(BaseModel):
    """A snapshot row for one issue/PR, used for attribution."""

    number: int
    labels: list[str] = Field(default_factory=list)
    is_pr: bool = False
    state: str = "open"
    merged: bool = False
    created_at: datetime
    closed_at: datetime | None = None


class FitnessContext(BaseModel):
    """Pure, data-only input to ``loop_fitness``. Carries NO live client."""

    model_config = {"frozen": True}

    window_start: datetime
    window_end: datetime
    worker_status: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[IssueRecord] = Field(default_factory=list)
    cost_usd: float | None = None


class LoopFitness(BaseModel):
    """One loop's fitness for one window. ``score`` is intra-loop only."""

    worker_name: str
    kind: FitnessKind
    score: float | None = None
    components: dict[str, float] = Field(default_factory=dict)
    sample_count: int = 0
    confidence: Confidence = Confidence.INSUFFICIENT_DATA
    notes: str | None = None
    timestamp: datetime
