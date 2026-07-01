"""Pure conformance model + check resolution/evaluation (ADR-0094).

Mirrors src/loop_fitness.py: pure functions over data, no I/O in the model
layer, replay-safe. Execution is injected via ConformanceRunnerPort so this
module never shells out. Sibling of ADR-0093's loop fitness — fitness for
architecture decisions instead of loops.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ConformanceKind(StrEnum):
    ENFORCED = "enforced"
    MANUAL = "manual"
    DECISION_OF_RECORD = "decision-of-record"


class CheckOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    MANUAL = "manual"
    SKIPPED = "skipped"
    UNRESOLVED = "unresolved"


class CheckResult(BaseModel):
    check: str
    outcome: CheckOutcome
    duration_s: float = 0.0
    detail: str | None = None


class AdrConformance(BaseModel):
    adr_id: str
    kind: ConformanceKind
    outcome: CheckOutcome
    checks: list[CheckResult] = Field(default_factory=list)
    timestamp: datetime


def classify_enforcement(raw: str) -> ConformanceKind | None:
    try:
        return ConformanceKind(raw.strip().lower())
    except ValueError:
        return None
