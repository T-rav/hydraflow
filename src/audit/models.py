"""Value objects for the sampled adversarial re-audit (#10370).

Mirrors ``escape.models``' style (frozen dataclasses; behavior limited to
derived helpers; mirror the sibling package's conventions rather than
cross-importing). Shapes:

* ``MergedChange`` — the sampler's input: one merged PR's metadata as a thin
  git adapter materializes it (PR number, merge sha, subject, changed paths).
  Synthetic in unit tests, no git dependency in the pure core.
* ``AuditSample`` — one append-only ``audit_samples.jsonl`` row: the fresh
  adversarial verdict on one sampled merge plus the input manifest that proves
  no original-verdict contamination.
* ``DisagreementObservation`` / ``FalseAlarmObservation`` — the two governance
  series (Shewhart rate control + auditor false-alarm budget).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

#: Blast-radius stratum of a merged change (decided v1 classes). ``routine`` is
#: the base stratum; the rest are elevated (higher sampling probability).
BlastRadiusClass = Literal[
    "routine",
    "structural",
    "security",
    "migration",
    "gauntlet",
]

#: The adversarial re-audit's verdict on one merged change.
AuditVerdict = Literal["agree", "disagree"]

#: Where a disagreement landed after the standard adjudication path.
#: ``pending`` = filed, awaiting adjudication; ``upheld`` = a silent escape
#: (crosses into the escape ledger); ``refuted`` = auditor false alarm;
#: ``n/a`` = an ``agree`` verdict (no disposition to resolve).
Disposition = Literal["n/a", "pending", "upheld", "refuted"]

#: The EXACT sources the fresh adversarial auditor is shown — the merged diff,
#: the linked spec/issue, and the current repo state. Deliberately EXCLUDES the
#: original gauntlet verdicts (fresh-context charter, decided). The audit row
#: records this manifest so no-contamination is verifiable from the record.
AUDIT_INPUT_SOURCES: tuple[str, ...] = (
    "merged-diff",
    "linked-spec-or-issue",
    "repo-state",
)

#: Cross-link detection source written into the escape ledger for an upheld
#: disagreement. A plain ``str`` value on ``EscapeRecord.detection_source`` (the
#: escape ledger's schema keeps that field open), so the cross-link reuses the
#: escape writer without forking its ``DetectionSource`` literal.
ESCAPE_DETECTION_SOURCE = "sampled-audit"


@dataclass(frozen=True)
class MergedChange:
    """One merged PR's metadata — the pure sampler's input.

    ``changed_paths`` are repo-root-relative paths the merge touched (any diff
    status), used for blast-radius classification. ``merged_at`` is an ISO-8601
    timestamp. ``pr_number`` is 0 when a merge commit carried no ``(#N)``.
    """

    pr_number: int
    merge_sha: str
    subject: str
    changed_paths: tuple[str, ...]
    merged_at: str
    body: str = ""

    @property
    def id(self) -> str:
        """Stable dedup key: one audit sample per (pr, merge sha) at most."""
        return f"{self.pr_number}:{self.merge_sha[:12]}"


@dataclass(frozen=True)
class AuditSample:
    """One append-only ``audit_samples.jsonl`` row.

    Records the fresh adversarial verdict on one sampled merge. ``input_sources``
    is the manifest of what the auditor saw — it must never contain an original-
    verdict token (see ``no_verdict_contamination``), which is how acceptance
    criterion 2 is verified straight from the record.
    """

    id: str
    audited_at: str
    pr_number: int
    merge_sha: str
    blast_radius_class: str
    verdict: str
    findings: str
    input_sources: tuple[str, ...]
    auditor_model: str
    sample_rate: float
    disposition: str = "pending"
    find_issue: int | None = None
    escape_id: str = ""

    def no_verdict_contamination(self) -> bool:
        """True when the input manifest carries no original-verdict token.

        The fresh-context charter forbids showing the auditor the original
        gauntlet verdicts; any manifest source mentioning ``verdict``/``gauntlet``
        /``review`` would be contamination. Pure, so acceptance criterion 2 is a
        unit assertion over the recorded row.
        """
        banned = ("verdict", "gauntlet", "original-review", "reviewer-verdict")
        return not any(
            any(bad in source.lower() for bad in banned)
            for source in self.input_sources
        )

    def to_json_dict(self) -> dict[str, Any]:
        """Canonical JSONL payload — stable field order."""
        return {
            "id": self.id,
            "audited_at": self.audited_at,
            "pr_number": self.pr_number,
            "merge_sha": self.merge_sha,
            "blast_radius_class": self.blast_radius_class,
            "verdict": self.verdict,
            "findings": self.findings,
            "input_sources": list(self.input_sources),
            "auditor_model": self.auditor_model,
            "sample_rate": self.sample_rate,
            "disposition": self.disposition,
            "find_issue": self.find_issue,
            "escape_id": self.escape_id,
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> AuditSample:
        """Parse one JSONL row, tolerant of missing optional fields."""
        return cls(
            id=str(raw.get("id", "")),
            audited_at=str(raw.get("audited_at", "")),
            pr_number=int(raw.get("pr_number", 0) or 0),
            merge_sha=str(raw.get("merge_sha", "")),
            blast_radius_class=str(raw.get("blast_radius_class", "routine")),
            verdict=str(raw.get("verdict", "agree")),
            findings=str(raw.get("findings", "")),
            input_sources=tuple(raw.get("input_sources", ()) or ()),
            auditor_model=str(raw.get("auditor_model", "")),
            sample_rate=float(raw.get("sample_rate", 0.0) or 0.0),
            disposition=str(raw.get("disposition", "pending")),
            find_issue=raw.get("find_issue"),
            escape_id=str(raw.get("escape_id", "")),
        )

    def with_disposition(
        self, disposition: Disposition, *, escape_id: str = ""
    ) -> AuditSample:
        """Return a copy with an adjudicated disposition (immutable update)."""
        return AuditSample(
            id=self.id,
            audited_at=self.audited_at,
            pr_number=self.pr_number,
            merge_sha=self.merge_sha,
            blast_radius_class=self.blast_radius_class,
            verdict=self.verdict,
            findings=self.findings,
            input_sources=self.input_sources,
            auditor_model=self.auditor_model,
            sample_rate=self.sample_rate,
            disposition=disposition,
            find_issue=self.find_issue,
            escape_id=escape_id or self.escape_id,
        )


@dataclass(frozen=True)
class DisagreementObservation:
    """One tick's disagreement reading — the Shewhart rate governor's input.

    ``sampled`` merged changes were audited this tick; ``disagreements`` of them
    drew a ``disagree`` verdict. Bucketed per tick so the p-chart's subgroup
    size is well defined.
    """

    sampled: int
    disagreements: int

    @property
    def proportion(self) -> float:
        """Disagreement proportion for this subgroup; ``0.0`` when nothing sampled."""
        if self.sampled <= 0:
            return 0.0
        return self.disagreements / self.sampled

    def to_json_dict(self) -> dict[str, int]:
        return {"sampled": self.sampled, "disagreements": self.disagreements}

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> DisagreementObservation:
        return cls(
            sampled=int(raw.get("sampled", 0) or 0),
            disagreements=int(raw.get("disagreements", 0) or 0),
        )


@dataclass(frozen=True)
class RateCI:
    """A proportion with a Wilson-score confidence interval."""

    rate: float
    lower: float
    upper: float
    n: int


@dataclass(frozen=True)
class GateClassCalibration:
    """Per-blast-radius-class calibration signal from the audit samples."""

    blast_radius_class: str
    sampled: int
    disagreements: int
    upheld: int

    @property
    def disagreement_rate(self) -> float:
        if self.sampled <= 0:
            return 0.0
        return self.disagreements / self.sampled


@dataclass(frozen=True)
class CalibrationSummary:
    """Everything the report + dashboard render for one audit rollup."""

    disagreement: RateCI
    false_alarm_rate: float
    per_gate_class: list[GateClassCalibration] = field(default_factory=list)
    total_samples: int = 0
    governed_rate: float = 0.0
