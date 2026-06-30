"""Gate referee abstraction for two-level convergence (ADR: two-level convergence)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from exception_classify import reraise_on_credit_or_bug
from review_advisor import min_review_passes_for_blast_radius


class GateDecision(StrEnum):
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


class HybridGate:
    """Deterministic-first, blast-radius-scaled judge referee (spec §4.2)."""

    def __init__(
        self,
        name: str,
        *,
        deterministic: Callable[[GateContext], Awaitable[DetResult]],
        judge: Callable[[GateContext, int], Awaitable[JudgeVerdict]],
        loop_back_target: str = "ready",
        fail_default_approve: bool = True,
    ) -> None:
        self.name = name
        self._deterministic = deterministic
        self._judge = judge
        self._loop_back_target = loop_back_target
        self._fail_default_approve = fail_default_approve

    async def evaluate(self, ctx: GateContext) -> GateResult:
        det = await self._deterministic(ctx)
        if not det.ok:
            return loop_back(
                self._loop_back_target, "; ".join(det.failures), det.signatures
            )

        n = min_review_passes_for_blast_radius(ctx.blast_radius)
        signatures = list(det.signatures)
        vetoed = False
        feedback: list[str] = []
        for i in range(n):
            try:
                verdict = await self._judge(ctx, i)
            except Exception as exc:  # noqa: BLE001
                reraise_on_credit_or_bug(exc)
                verdict = JudgeVerdict(
                    approve=self._fail_default_approve, feedback="judge-degraded"
                )
            signatures.extend(verdict.signatures)
            if not verdict.approve:
                vetoed = True
                if verdict.feedback:
                    feedback.append(verdict.feedback)

        if not vetoed:
            return advance(signatures)
        if ctx.attempts < ctx.max_attempts:
            return loop_back(self._loop_back_target, " | ".join(feedback), signatures)
        return escalate(
            f"judge veto after {ctx.max_attempts} attempts", signatures
        )


def build_review_gate(
    *,
    deterministic_check: Callable[[GateContext], Awaitable[DetResult]],
    post_verify_judge: Callable[[GateContext, int], Awaitable[JudgeVerdict]],
    fail_default_approve: bool = True,
) -> HybridGate:
    """Build the review-stage HybridGate (deterministic check + PostVerify judge).

    Binds the review deterministic signal and the post-verify judge into a
    gate that loops back to the ``ready`` stage on a recoverable veto.
    """
    return HybridGate(
        "review",
        deterministic=deterministic_check,
        judge=post_verify_judge,
        loop_back_target="ready",
        fail_default_approve=fail_default_approve,
    )
