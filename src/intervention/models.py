"""Value objects + the fixed v1 taxonomy for the intervention tally (#10369).

Mirrors ``escape.models``' style (frozen dataclasses, behavior limited to
derived helpers; mirror the sibling package's conventions rather than
cross-importing). Three shapes:

* ``InterventionSignal`` — the pure classifier's input: one raw human touch
  the factory already emitted (a steering directive, a HITL lifecycle event,
  a control-route action, a ``/hf`` CLI command), as a thin source adapter
  would materialize it. Synthetic in unit tests, no I/O in the core.
* ``InterventionCandidate`` — the classifier's reading: source folded into a
  taxonomy class + confidence. ``needs_llm`` marks a free-text steering
  signal the mechanical map could not resolve (the loop may upgrade it via a
  bounded cheap-LLM call; classification NEVER blocks the observed action).
* ``InterventionRecord`` — one append-only ledger row, the EXACT schema
  decided in ``docs/proposals/intervention-tally.md``: ``ts, source, class,
  confidence, loop_or_workflow, issue_or_pr, model_version_context, ref,
  notes`` (+ a derived ``id`` for dedup).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

#: The fixed v1 taxonomy (decided in the spec). ``approval`` is the lightest
#: class and is counted SEPARATELY so routine approve/deny never inflates the
#: correction rate. The other five are "correction-class" interventions.
InterventionClass = Literal[
    "objective-correction",
    "unstick",
    "instruction-violation",
    "quality-override",
    "steering-nudge",
    "approval",
]

#: All taxonomy classes, and the correction-class subset (everything but
#: ``approval``) — the rate that measures autonomy vs babysitting.
ALL_CLASSES: tuple[InterventionClass, ...] = (
    "objective-correction",
    "unstick",
    "instruction-violation",
    "quality-override",
    "steering-nudge",
    "approval",
)
CORRECTION_CLASSES: frozenset[str] = frozenset(
    c for c in ALL_CLASSES if c != "approval"
)

#: Where a human touch was sensed (v1 sources, decided). ``manual-git`` is a
#: known blind spot noted in the report, not a live source.
InterventionSource = Literal["steering", "hitl", "control-route", "cli"]

#: Confidence in the class assignment. Mechanical mappings are ``high``;
#: cheap-LLM verdicts carry their own confidence; free-text kept for re-label
#: is ``low``. Classification NEVER blocks — a ``low`` row is still a row.
Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class InterventionSignal:
    """One raw human touch — the pure classifier's input.

    ``kind`` is the source-specific mechanical hint (e.g. a HITL resolution
    code, a control-route action name, a steering ``flow`` value) the
    classifier maps to a taxonomy class. ``free_text`` carries an operator's
    free-form steering guidance when present (the only path that may reach the
    cheap-LLM classifier). ``ts`` is an ISO-8601 timestamp.
    """

    source: InterventionSource
    kind: str
    ts: str
    loop_or_workflow: str = ""
    issue_or_pr: str = ""
    ref: str = ""
    free_text: str = ""
    model_version_context: str = ""


@dataclass(frozen=True)
class InterventionCandidate:
    """The classifier's reading for one signal, pre-ledger.

    ``needs_llm`` is True only for a free-text steering signal the mechanical
    map left unresolved — the loop MAY upgrade it with one bounded cheap-LLM
    call, or (over budget / disabled) record it as a low-confidence
    ``steering-nudge`` keeping the raw text in ``notes`` for later re-label.
    """

    source: str
    intervention_class: InterventionClass
    confidence: Confidence
    ts: str
    loop_or_workflow: str = ""
    issue_or_pr: str = ""
    ref: str = ""
    model_version_context: str = ""
    notes: str = ""
    needs_llm: bool = False
    free_text: str = ""

    @property
    def id(self) -> str:
        """Stable dedup key: one row per (source, ref, ts) touch.

        Folds source + ref + ts so the same steering directive re-sensed
        across ticks (same ``last_applied_ts``) dedups to exactly one row,
        while a genuinely new touch on the same ref at a later ts is its own.
        """
        return f"{self.source}:{self.ref}:{self.ts}"


@dataclass(frozen=True)
class InterventionRecord:
    """One append-only intervention-ledger row (the EXACT decided schema)."""

    id: str
    ts: str
    source: str
    intervention_class: str
    confidence: str
    loop_or_workflow: str
    issue_or_pr: str
    model_version_context: str
    ref: str
    notes: str

    @classmethod
    def from_candidate(cls, candidate: InterventionCandidate) -> InterventionRecord:
        """Assemble a ledger row from a classified candidate."""
        return cls(
            id=candidate.id,
            ts=candidate.ts,
            source=candidate.source,
            intervention_class=candidate.intervention_class,
            confidence=candidate.confidence,
            loop_or_workflow=candidate.loop_or_workflow,
            issue_or_pr=candidate.issue_or_pr,
            model_version_context=candidate.model_version_context,
            ref=candidate.ref,
            notes=candidate.notes,
        )

    def to_json_dict(self) -> dict[str, Any]:
        """Canonical JSONL payload — field order matches the decided schema.

        The ``class`` key is spelled out literally (``intervention_class`` is
        the Python attribute; ``class`` is a reserved word) so the on-disk
        schema reads exactly as the spec decided it.
        """
        return {
            "id": self.id,
            "ts": self.ts,
            "source": self.source,
            "class": self.intervention_class,
            "confidence": self.confidence,
            "loop_or_workflow": self.loop_or_workflow,
            "issue_or_pr": self.issue_or_pr,
            "model_version_context": self.model_version_context,
            "ref": self.ref,
            "notes": self.notes,
        }

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> InterventionRecord:
        """Parse one JSONL row, tolerant of missing optional fields."""
        return cls(
            id=str(raw.get("id", "")),
            ts=str(raw.get("ts", "")),
            source=str(raw.get("source", "")),
            intervention_class=str(raw.get("class", "")),
            confidence=str(raw.get("confidence", "")),
            loop_or_workflow=str(raw.get("loop_or_workflow", "")),
            issue_or_pr=str(raw.get("issue_or_pr", "")),
            model_version_context=str(raw.get("model_version_context", "")),
            ref=str(raw.get("ref", "")),
            notes=str(raw.get("notes", "")),
        )
