"""Value objects for the escape ledger (#10367).

Mirrors ``erosion.models``' style (frozen dataclasses, behavior limited to
derived helpers; mirror the sibling package's conventions rather than
cross-importing). Three shapes:

* ``CommitInfo`` — the pure detector's input: one merged commit's metadata,
  as a thin git adapter would materialize it. Synthetic in unit tests, no git
  dependency in the core.
* ``EscapeCandidate`` — the detector's raw reading before attribution
  resolves the originating merge and time-to-detection.
* ``EscapeRecord`` — one append-only ledger row, the EXACT schema decided in
  ``docs/proposals/escape-ledger-and-erosion-trends.md``:
  ``id, detected_at, detection_source, detection_ref, originating_pr,
  originating_merge_sha, merged_at, time_to_detection_hours,
  attribution_method, attribution_confidence, encoded_as, notes``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

#: Where a post-merge defect surfaced (v1 detection sources, decided).
DetectionSource = Literal["sentry", "revert", "hotfix", "bug-issue", "regression-pin"]

#: How the ledger tied the escape back to the originating merge.
AttributionMethod = Literal[
    "revert-parse", "fixes-chain", "regression-pin", "blame-intersect", "agent-research"
]

#: Mechanical confidence in the attribution; ``low`` rows escalate to HITL
#: for a human label. Attribution NEVER blocks — a ``low`` row is still a row.
AttributionConfidence = Literal["high", "medium", "low"]

#: How the escape terminated in an encoding (every escape SHOULD). ``none-yet``
#: rows aging past a threshold are surfaced for human triage.
EncodedAs = Literal["regression-test", "stored-lesson", "detector", "adr", "none-yet"]


@dataclass(frozen=True)
class CommitInfo:
    """One merged commit's metadata — the pure escape detector's input.

    ``added_paths`` are repo-root-relative paths this commit *added* (git
    diff ``A`` status), used only for the regression-pin signal (a new file
    under ``tests/regressions/``). ``changed_paths`` are every path this
    commit touched (any status) — used to scope the Skip-Regression gate to
    genuinely product-source-empty commits (#10498) rather than trusting the
    trailer alone, which a legitimate non-docs opt-out (flaky-test fix,
    config-only fix) also carries. Empty when unknown (a synthetic
    ``CommitInfo`` or an adapter that hasn't populated it), in which case the
    gate fails open rather than guessing. ``committed_at`` is an ISO-8601
    timestamp.
    """

    sha: str
    subject: str
    body: str
    committed_at: str
    added_paths: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class EscapeCandidate:
    """The detector's raw reading for one detected escape, pre-attribution.

    ``originating_ref`` is the mechanical pointer the detector extracted (a
    reverted sha for reverts, or ``#N`` for a fixes-chain) — attribution
    resolves it to a concrete ``originating_merge_sha`` + ``merged_at``.
    Empty when the detector found no mechanical pointer (→ low confidence).
    """

    detection_source: DetectionSource
    detection_ref: str
    detected_at: str
    attribution_method: AttributionMethod
    attribution_confidence: AttributionConfidence
    originating_ref: str = ""
    originating_pr: int | None = None
    notes: str = ""

    @property
    def id(self) -> str:
        """Stable dedup key: one row per detecting commit/reference.

        Folds in the detection source so the same sha surfacing under two
        distinct sources (e.g. a revert that also adds a regression pin) is
        still deduped to the source that actually detected it.
        """
        return f"{self.detection_source}:{self.detection_ref}"


@dataclass(frozen=True)
class EscapeRecord:
    """One append-only escape-ledger row (the EXACT decided schema)."""

    id: str
    detected_at: str
    detection_source: str
    detection_ref: str
    originating_pr: int | None
    originating_merge_sha: str
    merged_at: str
    time_to_detection_hours: float | None
    attribution_method: str
    attribution_confidence: str
    encoded_as: str
    notes: str

    @classmethod
    def from_candidate(
        cls,
        candidate: EscapeCandidate,
        *,
        originating_merge_sha: str = "",
        merged_at: str = "",
        encoded_as: EncodedAs = "none-yet",
    ) -> EscapeRecord:
        """Assemble a ledger row, computing ``time_to_detection_hours``.

        Time-to-detection is ``detected_at - merged_at`` in hours when both
        timestamps parse; ``None`` otherwise (an unresolved originating
        merge, which is the honest reading — attribution never blocks).
        """
        ttd = _hours_between(merged_at, candidate.detected_at)
        return cls(
            id=candidate.id,
            detected_at=candidate.detected_at,
            detection_source=candidate.detection_source,
            detection_ref=candidate.detection_ref,
            originating_pr=candidate.originating_pr,
            originating_merge_sha=originating_merge_sha,
            merged_at=merged_at,
            time_to_detection_hours=ttd,
            attribution_method=candidate.attribution_method,
            attribution_confidence=candidate.attribution_confidence,
            encoded_as=encoded_as,
            notes=candidate.notes,
        )

    def to_json_dict(self) -> dict[str, Any]:
        """Canonical JSONL payload — field order matches the decided schema."""
        return {
            "id": self.id,
            "detected_at": self.detected_at,
            "detection_source": self.detection_source,
            "detection_ref": self.detection_ref,
            "originating_pr": self.originating_pr,
            "originating_merge_sha": self.originating_merge_sha,
            "merged_at": self.merged_at,
            "time_to_detection_hours": self.time_to_detection_hours,
            "attribution_method": self.attribution_method,
            "attribution_confidence": self.attribution_confidence,
            "encoded_as": self.encoded_as,
            "notes": self.notes,
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> EscapeRecord:
        """Parse one JSONL row, tolerant of missing optional fields."""
        return cls(
            id=str(raw.get("id", "")),
            detected_at=str(raw.get("detected_at", "")),
            detection_source=str(raw.get("detection_source", "")),
            detection_ref=str(raw.get("detection_ref", "")),
            originating_pr=raw.get("originating_pr"),
            originating_merge_sha=str(raw.get("originating_merge_sha", "")),
            merged_at=str(raw.get("merged_at", "")),
            time_to_detection_hours=raw.get("time_to_detection_hours"),
            attribution_method=str(raw.get("attribution_method", "")),
            attribution_confidence=str(raw.get("attribution_confidence", "")),
            encoded_as=str(raw.get("encoded_as", "none-yet")),
            notes=str(raw.get("notes", "")),
        )


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO-8601 timestamp, returning ``None`` on any malformed input."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _hours_between(start_iso: str, end_iso: str) -> float | None:
    """Hours from *start_iso* to *end_iso*, or ``None`` if either is unparseable."""
    start = _parse_iso(start_iso)
    end = _parse_iso(end_iso)
    if start is None or end is None:
        return None
    return (end - start).total_seconds() / 3600.0
