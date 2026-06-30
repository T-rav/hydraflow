"""Gate referee abstraction for two-level convergence (ADR: two-level convergence)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Protocol, runtime_checkable


class GateDecision(str, Enum):
    ADVANCE = "ADVANCE"
    LOOP_BACK = "LOOP_BACK"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class GateResult:
    decision: GateDecision
    target_stage: str | None = None
    feedback: str | None = None
    reason: str | None = None
    finding_signatures: list[str] = field(default_factory=list)


def advance(signatures: list[str] | None = None) -> GateResult:
    return GateResult(GateDecision.ADVANCE, finding_signatures=list(signatures or []))


def loop_back(
    target: str, feedback: str, signatures: list[str] | None = None
) -> GateResult:
    return GateResult(
        GateDecision.LOOP_BACK,
        target_stage=target,
        feedback=feedback,
        finding_signatures=list(signatures or []),
    )


def escalate(reason: str, signatures: list[str] | None = None) -> GateResult:
    return GateResult(
        GateDecision.ESCALATE, reason=reason, finding_signatures=list(signatures or [])
    )


@dataclass
class GateContext:
    issue_number: int
    stage: str
    blast_radius: Literal["low", "medium", "high"]
    attempts: int
    max_attempts: int


@dataclass(frozen=True)
class DetResult:
    ok: bool
    failures: list[str] = field(default_factory=list)
    signatures: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class JudgeVerdict:
    approve: bool
    feedback: str | None = None
    signatures: list[str] = field(default_factory=list)


@runtime_checkable
class Gate(Protocol):
    name: str

    async def evaluate(self, ctx: GateContext) -> GateResult: ...
