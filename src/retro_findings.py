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

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from retro_signals import RetroSignal

# A GATE finding proposes a guard. It may not exist yet, so only its location
# is checked — these are the three places this repo enforces from.
GUARD_PREFIXES = (
    "tests/architecture/",
    ".claude/hooks/",
    ".github/workflows/",
)

NonEmpty = Annotated[str, Field(min_length=1)]


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
    return _policy_reason(finding, repo_root)


def _gate_reason(finding: GateFinding, signal: RetroSignal) -> str | None:
    if not _is_safe_relative(finding.guard_path):
        return f"guard_path is not a safe repo-relative path: {finding.guard_path!r}"
    if not finding.guard_path.startswith(GUARD_PREFIXES):
        return (
            f"guard_path {finding.guard_path!r} is outside the guard allowlist "
            f"{GUARD_PREFIXES}"
        )
    if str(signal.count) not in finding.observed:
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
