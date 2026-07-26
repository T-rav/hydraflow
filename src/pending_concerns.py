from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
Phase = Literal["discover", "shape", "plan", "implement", "post_merge"]
ResolutionKind = Literal[
    "trivial", "deferred", "addressed-in-code", "addressed-in-test", "ignored"
]


class Concern(BaseModel):
    id: str
    raised_in_phase: Phase
    raised_in_stage: str
    severity: Severity
    concern: str
    raised_at: datetime
    must_address_by: str
    human_required: bool = False


class ConcernResolution(BaseModel):
    concern_id: str
    addressed_in_stage: str
    resolution: str
    addressed_at: datetime
    resolution_kind: ResolutionKind


class StageRun(BaseModel):
    stage: str
    phase: Phase
    retries: int
    converged: bool
    concerns_raised: int
    concerns_forwarded: int
    oscillation_detected: bool
    duration_ms: int


class AdversarialState(BaseModel):
    phase: Phase
    current_stage: str | None = None
    pending_concerns: list[Concern] = Field(default_factory=list)
    addressed_concerns: list[ConcernResolution] = Field(default_factory=list)
    stage_history: list[StageRun] = Field(default_factory=list)


# Plan-review stages whose CRITICAL findings signal an *unresolved design
# decision / unvalidated core mechanism* — something a human must decide
# (brainstorm -> spec) before implementation, NOT something the implementer can
# address in code. The Risk-Skeptic ("should this exist / is the motivating
# assumption verifiable / is the core mechanism validated") and the
# AssumptionSurfacer ("what uncertainty is unresolved") occupy this design-gate
# role. The Builder (buildability), Tester (coverage), and SpecJudge (AC
# compliance) stages are implementer-addressable and are deliberately excluded
# so ordinary fixable-concern plans keep flowing to ``ready`` (issue #10659).
DESIGN_DECISION_STAGES: frozenset[str] = frozenset(
    {"plan_council_risk_skeptic", "assumption_surfacer"}
)


def is_design_decision_concern(concern: Concern) -> bool:
    """Return True if *concern* needs a human DESIGN DECISION before implementation.

    A concern qualifies when it is either

    * explicitly tagged ``human_required`` (any severity/stage), or
    * a ``CRITICAL`` finding raised by a design-gate stage
      (``DESIGN_DECISION_STAGES``) — i.e. "should this exist / is the core
      mechanism validated", as opposed to "the implementer should tidy this up".

    Everything else (buildability, test-coverage, acceptance-criteria, or any
    non-CRITICAL finding) is treated as implementer-addressable and does NOT
    qualify — see issue #10659.
    """
    if concern.human_required:
        return True
    return (
        concern.severity == "CRITICAL"
        and concern.raised_in_stage in DESIGN_DECISION_STAGES
    )


def count_design_decision_concerns(concerns: Iterable[Concern]) -> int:
    """Count concerns that need a human design decision (issue #10659)."""
    return sum(1 for c in concerns if is_design_decision_concern(c))
