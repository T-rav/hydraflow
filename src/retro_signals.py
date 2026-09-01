"""Deterministic signal extraction from gathered retro evidence.

Signals quantify what went wrong across a window of issues. They are the only
grounding the LLM finder stage may cite, and each carries the literal evidence
text the validator resolves a finding's excerpt against.

Pure: no I/O, no subprocess, no clock.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from signature_normalize import normalize_signature

if TYPE_CHECKING:
    from collections.abc import Sequence

    from models import SubprocessTrace
    from retro_evidence import RetroEvidence

SignalFamily = Literal[
    "tool_error", "crash", "skill_failure", "tool_thrash", "transcript_failure"
]

# A tool repeating the same summarized input this many times in one subprocess
# is the edit-retry loop shape, not normal work.
THRASH_THRESHOLD = 4


class EvidenceRef(BaseModel):
    """A pointer to, and a verbatim slice of, the evidence behind a signal."""

    locator: str
    excerpt: str


class RetroSignal(BaseModel):
    id: str
    family: SignalFamily
    signature: str
    count: int
    issues: list[int] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class _Accumulator:
    """Groups occurrences under one signature, preserving first evidence."""

    def __init__(self) -> None:
        self.count = 0
        self.issues: set[int] = set()
        self.evidence: list[EvidenceRef] = []

    def add(self, issue: int, ref: EvidenceRef | None) -> None:
        self.count += 1
        self.issues.add(issue)
        if ref is not None and len(self.evidence) < 3:
            self.evidence.append(ref)


def _signal_id(family: str, signature: str) -> str:
    digest = hashlib.sha256(
        f"{family}:{signature}".encode(), usedforsecurity=False
    ).hexdigest()
    return f"{family}-{digest[:10]}"


def extract(bundles: Sequence[RetroEvidence]) -> list[RetroSignal]:
    """Quantify failure signals across a window of issues."""
    groups: dict[tuple[SignalFamily, str], _Accumulator] = defaultdict(_Accumulator)

    for bundle in bundles:
        for trace in bundle.traces:
            _tool_errors(bundle.issue_number, trace, groups)
            _crashes(bundle.issue_number, trace, groups)
            _skill_failures(bundle.issue_number, trace, groups)
            _tool_thrash(bundle.issue_number, trace, groups)

    return [
        RetroSignal(
            id=_signal_id(family, signature),
            family=family,
            signature=signature,
            count=acc.count,
            issues=sorted(acc.issues),
            evidence=acc.evidence,
        )
        for (family, signature), acc in groups.items()
    ]


def _locator(trace: SubprocessTrace, suffix: str) -> str:
    return (
        f"traces/{trace.issue_number}/{trace.phase}/run-{trace.run_id}/"
        f"subprocess-{trace.subprocess_idx}.json#{suffix}"
    )


def _tool_errors(issue, trace, groups) -> None:
    """Keyed on ``error``, never on ``succeeded``.

    A Codex span ends ``succeeded=False, error=None`` because Codex has no
    completion handler — never closed, not failed. Keying on ``succeeded``
    would score every Codex tool call as a failure.
    """
    for span in trace.tool_calls:
        if span.error is None:
            continue
        signature = f"{span.tool_name}: {normalize_signature(span.error)}"
        groups[("tool_error", signature)].add(
            issue,
            EvidenceRef(locator=_locator(trace, span.tool_name), excerpt=span.error),
        )


def _crashes(issue, trace, groups) -> None:
    if not trace.crashed:
        return
    detail = normalize_signature(trace.error or "no error text")
    signature = f"{trace.phase}: {detail}"
    ref = (
        EvidenceRef(locator=_locator(trace, "error"), excerpt=trace.error)
        if trace.error
        else None
    )
    groups[("crash", signature)].add(issue, ref)


def _skill_failures(issue, trace, groups) -> None:
    """No excerpt: SkillResultRecord carries no error text, so a skill failure
    can ground a GATE or POLICY finding but never a BUGFIX."""
    for skill in trace.skill_results:
        if skill.passed:
            continue
        groups[("skill_failure", f"{skill.skill_name} failed")].add(issue, None)


def _tool_thrash(issue, trace, groups) -> None:
    repeats: dict[tuple[str, str], int] = defaultdict(int)
    for span in trace.tool_calls:
        repeats[(span.tool_name, span.input_summary)] += 1

    for (tool, summary), n in repeats.items():
        if n < THRASH_THRESHOLD:
            continue
        signature = f"{tool} repeated identical input: {normalize_signature(summary)}"
        acc = groups[("tool_thrash", signature)]
        acc.count += n
        acc.issues.add(issue)
        if len(acc.evidence) < 3:
            acc.evidence.append(
                EvidenceRef(locator=_locator(trace, tool), excerpt=summary)
            )
