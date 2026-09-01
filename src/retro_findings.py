"""Typed retrospective findings and the validator that gates them.

The retro used to emit prose — "consider strengthening the implementation
prompt". The fix is structural rather than a prompt asking for specificity:

* every finding kind declares required, non-empty anchor fields, so a vague
  finding is unconstructable rather than merely low-quality;
* every anchor is then resolved against the real tree and the real evidence, so
  an invented path or a hallucinated error string is dropped and counted.

Pure: filesystem reads for existence only, no network, no subprocess.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from retro_signals import RetroSignal

# A GATE finding proposes a guard. It may not exist yet, so only its location
# is checked — these are the three places this repo enforces from.
GUARD_PREFIXES = (
    "tests/architecture/",
    ".claude/hooks/",
    ".github/workflows/",
)

# `min_length=1` alone counts a single space as content — a POLICY finding
# whose whole rule_text was " " constructed, validated, and was kept, which is
# exactly the vagueness these anchors exist to prevent (review pass three).
# Strip first, THEN require length, so whitespace collapses to "" and is
# rejected; padded anchors are stored trimmed rather than trusted as typed.
NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _FindingBase(BaseModel):
    signal_id: NonEmpty
    title: NonEmpty
    rationale: str = ""


class GateFinding(_FindingBase):
    """Proposes a guard, anchored to a location and a quantified observation."""

    kind: Literal["gate"]
    guard_path: NonEmpty
    observed: NonEmpty


class BugfixFinding(_FindingBase):
    """Proposes a fix, anchored to a repro and a verbatim observed error."""

    kind: Literal["bugfix"]
    repro_command: NonEmpty
    repro_file: NonEmpty
    error_excerpt: NonEmpty


class PolicyFinding(_FindingBase):
    """Proposes a rule amending an existing document."""

    kind: Literal["policy"]
    doc_path: NonEmpty
    rule_text: NonEmpty


RetroFinding = Annotated[
    GateFinding | BugfixFinding | PolicyFinding,
    Field(discriminator="kind"),
]


class DroppedFinding(BaseModel):
    """A finding that failed anchor resolution, with the reason it failed."""

    title: str
    kind: str
    reason: str


def _is_safe_relative(raw: str) -> bool:
    path = Path(raw)
    if path.is_absolute():
        return False
    return ".." not in path.parts


def _resolves(repo_root: Path, raw: str) -> bool:
    return (repo_root / raw).exists()


def validate(
    findings: list[RetroFinding],
    signals: list[RetroSignal],
    repo_root: Path,
) -> tuple[list[RetroFinding], list[DroppedFinding]]:
    """Split *findings* into those whose anchors resolve and those that fail.

    Nothing is silently discarded: every rejection carries its reason so a
    model that starts confabulating shows up as a rising drop rate rather than
    as issue spam.
    """
    by_id = {s.id: s for s in signals}
    kept: list[RetroFinding] = []
    dropped: list[DroppedFinding] = []

    for finding in findings:
        reason = _rejection_reason(finding, by_id, repo_root)
        if reason is None:
            kept.append(finding)
        else:
            dropped.append(
                DroppedFinding(title=finding.title, kind=finding.kind, reason=reason)
            )

    return kept, dropped


def _rejection_reason(
    finding: RetroFinding, by_id: dict[str, RetroSignal], repo_root: Path
) -> str | None:
    signal = by_id.get(finding.signal_id)
    if signal is None:
        return f"cites unknown signal {finding.signal_id!r}"

    if isinstance(finding, GateFinding):
        return _gate_reason(finding, signal)
    if isinstance(finding, BugfixFinding):
        return _bugfix_reason(finding, signal, repo_root)
    if isinstance(finding, PolicyFinding):
        return _policy_reason(finding, repo_root)
    # A new finding kind must declare its own checks. Falling through to the
    # policy path would silently validate it against the wrong anchors.
    return f"unrecognised finding kind {finding.kind!r} has no validation"


def _gate_reason(finding: GateFinding, signal: RetroSignal) -> str | None:
    if not _is_safe_relative(finding.guard_path):
        return f"guard_path is not a safe repo-relative path: {finding.guard_path!r}"
    if not finding.guard_path.startswith(GUARD_PREFIXES):
        return (
            f"guard_path {finding.guard_path!r} is outside the guard allowlist "
            f"{GUARD_PREFIXES}"
        )
    # Word-boundary, not substring: a bare `in` test let count=7 pass on
    # "took 70 seconds" and count=2 on any 2026 date. Counts are small
    # integers and model prose is full of numbers, so the substring form was
    # nearly free to satisfy — and it is the ONLY thing forcing a GATE finding
    # to be quantified.
    if not re.search(rf"(?<!\d){re.escape(str(signal.count))}(?!\d)", finding.observed):
        return (
            f"observed does not restate the signal count {signal.count} — "
            "a prose-only observation is not evidence"
        )
    return None


def _bugfix_reason(
    finding: BugfixFinding, signal: RetroSignal, repo_root: Path
) -> str | None:
    if not _is_safe_relative(finding.repro_file):
        return f"repro_file is not a safe repo-relative path: {finding.repro_file!r}"
    if not _resolves(repo_root, finding.repro_file):
        return f"repro_file does not exist: {finding.repro_file!r}"
    if not any(finding.error_excerpt in ref.excerpt for ref in signal.evidence):
        return "error_excerpt does not appear verbatim in the cited signal's evidence"
    return None


def _policy_reason(finding: PolicyFinding, repo_root: Path) -> str | None:
    if not _is_safe_relative(finding.doc_path):
        return f"doc_path is not a safe repo-relative path: {finding.doc_path!r}"
    if not _resolves(repo_root, finding.doc_path):
        return f"doc_path does not exist: {finding.doc_path!r}"
    return None
