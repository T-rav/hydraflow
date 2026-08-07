"""Spec intake gate (#10830) — stress-test prose before it becomes a setpoint.

The `advisory-review-then-refine-then-plan` pass (a read-only Opus read of each
spec against the real code before planning) already does this by hand, but has no
recorded verdict and no trend, so it cannot say whether specs are improving or
degrading — and it runs only when a human remembers. This turns it into an
instrument: an event-triggered gate that records verdicts and never edits the
spec (proposal-only write surface).

Load-bearing design rulings this module encodes (from the issue's guardrails):

1. **Two divergence classes, never one score.** "Contradicted by fact" (a defect)
   and "diverges from established practice" (useful output — HydraFlow's own ADRs
   carry the genuinely novel material a consensus check would flag as a defect)
   stay separate. See :class:`DivergenceKind`.
2. **No aggregate score.** A mean over findings destroys severity and dependency
   (and scores invite gaming). The headline is the *max* severity over the
   load-bearing assertions — :attr:`SpecIntakeVerdict.headline_severity` — never a
   blended number.
3. **A falsifiability companion metric is required.** A document with no checkable
   claims passes any stress test perfectly, so a claim-free spec must be
   *flaggable* — otherwise the gate trains authors toward mush. This is the one
   part computed deterministically here (:func:`falsifiability_report`); the three
   contradiction checks and the unstated-assumption surfacing are model work,
   injected behind the :class:`SpecReviewer` seam.

The deterministic core (schema + falsifiability + max-severity aggregation +
ledger) is live today; the model reviewer is a Phase-2 seam, and golden-baseline
calibration of the prose critic (#10821 — a generative sensor has no natural zero)
is a documented follow-up.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class Severity(StrEnum):
    """Severity of a load-bearing assertion or contradiction (ordered)."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_SEVERITY_ORDER = (Severity.INFO, Severity.LOW, Severity.MEDIUM, Severity.HIGH)


def max_severity(severities: Sequence[Severity]) -> Severity:
    """The highest severity in a sequence (INFO when empty).

    This is the headline aggregation — deliberately *max*, never a mean: a mean
    over findings destroys the one high-severity load-bearing claim in a sea of
    trivia (the failure the no-aggregate-score ruling exists to prevent).
    """
    return max(severities, key=_SEVERITY_ORDER.index, default=Severity.INFO)


class ContradictionKind(StrEnum):
    """The three distinct contradiction checks — reported separately."""

    INTERNAL = "internal"  # the document contradicts itself
    CORPUS = "corpus"  # conflicts with a live ADR / spec (semantic, not label-drift)
    CODE = "code"  # asserts behaviour the repository does not have


class DivergenceKind(StrEnum):
    """Divergence from established practice — kept in TWO separate classes.

    ``CONTRADICTED_BY_FACT`` is a defect. ``DIVERGES_FROM_PRACTICE`` is *not* — it
    is where genuinely novel material lives (plant-edits-controller, generative
    sensors), and collapsing the two into one consensus score would flag the
    contributions as defects. Divergent-but-uncontradicted feeds the lineage pass.
    """

    CONTRADICTED_BY_FACT = "contradicted_by_fact"
    DIVERGES_FROM_PRACTICE = "diverges_from_practice"


@dataclass(frozen=True)
class Contradiction:
    """One contradiction finding from the model reviewer."""

    kind: ContradictionKind
    severity: Severity
    quote: str  # the offending span, verbatim (proposal-only: never edited)
    explanation: str


@dataclass(frozen=True)
class Divergence:
    """A divergence from established practice — fact vs practice kept separate."""

    kind: DivergenceKind
    quote: str
    explanation: str


@dataclass(frozen=True)
class LoadBearingAssertion:
    """A claim the implementation would depend on — blast radius applied to prose."""

    claim: str
    severity: Severity


# --- Falsifiability / claim-density (the required deterministic companion) ---

# A sentence is *checkable* when it carries at least one falsifiable marker: a
# normative keyword, a code span, a file path, a number, or a named symbol.
_NORMATIVE_RE = re.compile(
    r"\b(MUST NOT|MUST|SHALL NOT|SHALL|REQUIRED|NEVER|ALWAYS|EXACTLY)\b"
)
_CODE_SPAN_RE = re.compile(r"`[^`]+`")
_PATH_RE = re.compile(r"\b(?:src|tests|docs|scripts)/[\w./-]+")
_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
_SYMBOL_RE = re.compile(r"\b[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*\b|[A-Z][a-z]+[A-Z]\w+")

# Hedge words mark a vague, unfalsifiable sentence when no checkable marker is
# present. Deliberately the softeners that let prose assert nothing checkable.
_HEDGE_RE = re.compile(
    r"\b(should|might|may|could|generally|typically|usually|appropriate|"
    r"reasonable|robust|clean|simple|properly|efficiently|as needed|"
    r"as appropriate|where possible|if necessary|etc\.?)\b",
    re.IGNORECASE,
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_MIN_SENTENCE_CHARS = 12


def _sentences(text: str) -> list[str]:
    """Split prose into candidate statements, dropping trivially short ones."""
    parts = (s.strip(" \t-*>#").strip() for s in _SENTENCE_SPLIT_RE.split(text))
    return [s for s in parts if len(s) >= _MIN_SENTENCE_CHARS]


def is_checkable(sentence: str) -> bool:
    """True when a sentence carries at least one falsifiable marker."""
    return bool(
        _NORMATIVE_RE.search(sentence)
        or _CODE_SPAN_RE.search(sentence)
        or _PATH_RE.search(sentence)
        or _NUMBER_RE.search(sentence)
        or _SYMBOL_RE.search(sentence)
    )


@dataclass(frozen=True)
class FalsifiabilityReport:
    """How much of a document makes checkable claims (the anti-mush metric).

    ``claim_density`` is the fraction of statements that carry a falsifiable
    marker. A low density on a document that *reads* substantive is the mush
    signal #10829 exists to catch — a spec that asserts nothing checkable passes
    any stress test perfectly. ``mushiest`` lists the hedge-heavy, claim-free
    statements to revise first.
    """

    total_statements: int
    checkable_count: int
    claim_density: float
    hedge_only_count: int
    mushiest: tuple[str, ...]


def falsifiability_report(
    text: str, *, mushiest_limit: int = 5
) -> FalsifiabilityReport:
    """Deterministic claim-density measure over a document's prose."""
    sentences = _sentences(text)
    total = len(sentences)
    if total == 0:
        return FalsifiabilityReport(0, 0, 0.0, 0, ())
    checkable = [s for s in sentences if is_checkable(s)]
    # "Mushy" = a hedge with no checkable marker: it asserts nothing verifiable.
    hedge_only = [s for s in sentences if _HEDGE_RE.search(s) and not is_checkable(s)]
    return FalsifiabilityReport(
        total_statements=total,
        checkable_count=len(checkable),
        claim_density=len(checkable) / total,
        hedge_only_count=len(hedge_only),
        mushiest=tuple(hedge_only[:mushiest_limit]),
    )


# --- The verdict + the injected model seam ----------------------------------


@dataclass(frozen=True)
class SpecIntakeVerdict:
    """The recorded verdict for one spec/ADR/proposal. No aggregate score."""

    subject_id: str  # e.g. "adr:0130" or "spec:2026-08-05-foo"
    contradictions: tuple[Contradiction, ...]
    divergences: tuple[Divergence, ...]
    load_bearing_assertions: tuple[LoadBearingAssertion, ...]
    unstated_assumptions: tuple[str, ...]
    falsifiability: FalsifiabilityReport

    @property
    def headline_severity(self) -> Severity:
        """Max severity over load-bearing assertions — the headline (never a mean)."""
        return max_severity([a.severity for a in self.load_bearing_assertions])

    @property
    def has_contradictions(self) -> bool:
        return bool(self.contradictions)


@dataclass(frozen=True)
class SpecReview:
    """The model reviewer's structured output (the injected, non-deterministic part)."""

    contradictions: tuple[Contradiction, ...] = ()
    divergences: tuple[Divergence, ...] = ()
    load_bearing_assertions: tuple[LoadBearingAssertion, ...] = ()
    unstated_assumptions: tuple[str, ...] = ()


class SpecReviewer(Protocol):
    """The injected model seam: the three contradiction checks + assumption
    surfacing over a document against the live corpus + code. Phase-2 wiring
    routes this to an out-of-family Opus read (judge-independence); the
    deterministic falsifiability metric needs no reviewer and runs regardless."""

    def review(self, document: str, *, subject_id: str) -> SpecReview: ...


def assess(
    document: str,
    *,
    subject_id: str,
    reviewer: SpecReviewer | None = None,
) -> SpecIntakeVerdict:
    """Assess one document: the deterministic falsifiability metric always, plus
    the model reviewer's contradiction/divergence/assumption findings when a
    reviewer is injected. Never edits the document (proposal-only)."""
    falsifiability = falsifiability_report(document)
    review = (
        reviewer.review(document, subject_id=subject_id) if reviewer else SpecReview()
    )
    return SpecIntakeVerdict(
        subject_id=subject_id,
        contradictions=review.contradictions,
        divergences=review.divergences,
        load_bearing_assertions=review.load_bearing_assertions,
        unstated_assumptions=review.unstated_assumptions,
        falsifiability=falsifiability,
    )


# --- Append-only verdict ledger ---------------------------------------------

SPEC_INTAKE_SUBDIR = "spec_intake"
VERDICTS_FILENAME = "spec_intake_verdicts.jsonl"


def spec_intake_ledger_path(data_root):
    """``<data_root>/spec_intake/spec_intake_verdicts.jsonl`` (mirrors the
    calibration-ledger convention)."""
    from pathlib import Path

    return Path(data_root) / SPEC_INTAKE_SUBDIR / VERDICTS_FILENAME


@dataclass
class VerdictRow:
    """One ledger row: the verdict counts + falsifiability, content-light."""

    subject_id: str
    recorded_at: str
    headline_severity: str
    contradiction_count: int
    diverges_from_practice_count: int
    load_bearing_count: int
    unstated_assumption_count: int
    claim_density: float
    mush_flagged: bool = field(default=False)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "subject_id": self.subject_id,
            "recorded_at": self.recorded_at,
            "headline_severity": self.headline_severity,
            "contradiction_count": self.contradiction_count,
            "diverges_from_practice_count": self.diverges_from_practice_count,
            "load_bearing_count": self.load_bearing_count,
            "unstated_assumption_count": self.unstated_assumption_count,
            "claim_density": self.claim_density,
            "mush_flagged": self.mush_flagged,
        }


#: A document whose checkable-claim density falls below this reads as mush —
#: the failure mode a falsifiability metric exists to flag.
MUSH_DENSITY_FLOOR = 0.25


def verdict_row(verdict: SpecIntakeVerdict, *, recorded_at: str) -> VerdictRow:
    """Reduce a verdict to its content-light ledger row."""
    fals = verdict.falsifiability
    diverges = sum(
        1
        for d in verdict.divergences
        if d.kind is DivergenceKind.DIVERGES_FROM_PRACTICE
    )
    return VerdictRow(
        subject_id=verdict.subject_id,
        recorded_at=recorded_at,
        headline_severity=verdict.headline_severity.value,
        contradiction_count=len(verdict.contradictions),
        diverges_from_practice_count=diverges,
        load_bearing_count=len(verdict.load_bearing_assertions),
        unstated_assumption_count=len(verdict.unstated_assumptions),
        claim_density=fals.claim_density,
        mush_flagged=fals.total_statements > 0
        and fals.claim_density < MUSH_DENSITY_FLOOR,
    )
