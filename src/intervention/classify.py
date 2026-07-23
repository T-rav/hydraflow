"""Pure intervention classification (#10369).

``classify`` is the pure core: it reads a list of ``InterventionSignal`` and
returns one ``InterventionCandidate`` per signal — mirroring
``escape.detect.detect_escapes``' purity contract (explicit inputs, no I/O,
unit-testable with synthetic data). Two classification paths, both decided in
the spec:

* **Mechanical mapping** — where the source implies the class (HITL
  resolution codes, control-route action names, a steering ``flow`` value, a
  ``/hf`` command name), a static map assigns the class at ``high``
  confidence. This is the dominant path and needs no LLM.
* **Cheap-LLM (free-text steering only)** — a steering directive carrying
  free-form ``guidance`` with no mechanical hint is marked ``needs_llm`` and
  defaulted to a low-confidence ``steering-nudge`` keeping the raw text. The
  loop MAY upgrade it with one bounded cheap-LLM call and ``parse_llm_verdict``
  turns that raw reply into ``(class, confidence)``. Classification NEVER
  blocks the observed action; over budget / disabled, the low-confidence
  default stands and the raw text is preserved for later re-label.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import cast

from intervention.models import (
    ALL_CLASSES,
    Confidence,
    InterventionCandidate,
    InterventionClass,
    InterventionSignal,
)

#: Mechanical source→class map, keyed ``"{source}:{kind}"`` (decided). Every
#: v1 signal whose source implies its class resolves here at high confidence.
MECHANICAL_CLASS: dict[str, InterventionClass] = {
    # HITL escalation lifecycle — resolution codes imply the class.
    "hitl:approved": "approval",
    "hitl:approve": "approval",
    "hitl:denied": "approval",
    "hitl:deny": "approval",
    "hitl:rejected": "approval",
    "hitl:resolved": "unstick",
    "hitl:unstuck": "unstick",
    "hitl:escalation_resolved": "unstick",
    "hitl:redirected": "objective-correction",
    "hitl:reassigned": "objective-correction",
    "hitl:quality_reject": "quality-override",
    "hitl:reverted": "quality-override",
    # Dashboard control-route actions — action name implies the class.
    "control-route:pause": "unstick",
    "control-route:resume": "unstick",
    "control-route:abort": "unstick",
    "control-route:restart": "unstick",
    "control-route:retry": "unstick",
    "control-route:skip": "objective-correction",
    "control-route:reroute": "objective-correction",
    "control-route:approve": "approval",
    "control-route:reject": "quality-override",
    # ``/hf`` CLI administrative commands.
    "cli:pause": "unstick",
    "cli:resume": "unstick",
    "cli:abort": "unstick",
    "cli:redo": "objective-correction",
    "cli:approve": "approval",
    "cli:kill": "unstick",
    # Steering directives whose ``flow`` value is itself mechanical.
    "steering:abort": "unstick",
    "steering:paused": "unstick",
    "steering:redo": "objective-correction",
    "steering:nudge": "steering-nudge",
}

#: The class a free-text steering directive defaults to before any LLM upgrade
#: (routine mid-flight directive — the existing steering grammar's base case).
_FREE_TEXT_DEFAULT: InterventionClass = "steering-nudge"

_VALID_CLASSES: frozenset[str] = frozenset(ALL_CLASSES)
_VALID_CONFIDENCE: frozenset[str] = frozenset({"high", "medium", "low"})


def _mechanical_key(signal: InterventionSignal) -> str:
    return f"{signal.source}:{signal.kind}"


def classify_one(signal: InterventionSignal) -> InterventionCandidate:
    """Classify a single signal (pure).

    Mechanical hit → high-confidence class. A steering signal carrying
    free-text guidance with no mechanical hit → a ``needs_llm`` low-confidence
    ``steering-nudge`` keeping the raw text (the loop may upgrade it). Any
    other unmapped signal → low-confidence ``steering-nudge`` as the honest
    catch-all (still recorded — classification never drops a human touch).
    """
    mapped = MECHANICAL_CLASS.get(_mechanical_key(signal))
    if mapped is not None:
        return InterventionCandidate(
            source=signal.source,
            intervention_class=mapped,
            confidence="high",
            ts=signal.ts,
            loop_or_workflow=signal.loop_or_workflow,
            issue_or_pr=signal.issue_or_pr,
            ref=signal.ref,
            model_version_context=signal.model_version_context,
            notes=signal.free_text,
            needs_llm=False,
            free_text=signal.free_text,
        )

    free_text = signal.free_text.strip()
    needs_llm = signal.source == "steering" and bool(free_text)
    return InterventionCandidate(
        source=signal.source,
        intervention_class=_FREE_TEXT_DEFAULT,
        confidence="low",
        ts=signal.ts,
        loop_or_workflow=signal.loop_or_workflow,
        issue_or_pr=signal.issue_or_pr,
        ref=signal.ref,
        model_version_context=signal.model_version_context,
        notes=free_text,
        needs_llm=needs_llm,
        free_text=free_text,
    )


def classify(signals: list[InterventionSignal]) -> list[InterventionCandidate]:
    """Pure: one ``InterventionCandidate`` per signal, order-preserving."""
    return [classify_one(signal) for signal in signals]


def build_classification_prompt(free_text: str) -> str:
    """Cheap-LLM prompt to classify one free-text steering directive.

    Kept pure + tiny (the spend budget is why free-text is the ONLY LLM path).
    """
    classes = ", ".join(ALL_CLASSES)
    return (
        "Classify this human steering directive to a factory into exactly one "
        f"intervention class from: {classes}.\n\n"
        "Definitions: objective-correction = redirected the goal/plan; "
        "unstick = freed a wedged/looping/stalled loop; instruction-violation "
        "= corrected something done against instructions; quality-override = "
        "caught bad output that passed the gates; steering-nudge = routine "
        "mid-flight directive; approval = routine approve/deny.\n\n"
        f"Directive:\n{free_text}\n\n"
        'Reply with ONLY compact JSON: {"class": "<one class>", '
        '"confidence": "high|medium|low"}.'
    )


def parse_llm_verdict(raw: str) -> tuple[InterventionClass, Confidence] | None:
    """Parse a cheap-LLM reply into ``(class, confidence)``; ``None`` if invalid.

    Tolerant of a fenced or chatty reply: extracts the first ``{...}`` object.
    Returns ``None`` (caller keeps the low-confidence default) on any parse
    failure or an out-of-taxonomy class — an unparseable verdict must never
    invent a class, and it never blocks.
    """
    obj = _extract_json_object(raw)
    if obj is None:
        return None
    klass = str(obj.get("class", "")).strip()
    conf = str(obj.get("confidence", "")).strip().lower()
    if klass not in _VALID_CLASSES:
        return None
    if conf not in _VALID_CONFIDENCE:
        conf = "medium"
    return cast("InterventionClass", klass), cast("Confidence", conf)


def _extract_json_object(raw: str) -> dict[str, object] | None:
    """Extract the first top-level JSON object from *raw*, or ``None``."""
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def apply_verdict(
    candidate: InterventionCandidate,
    verdict: tuple[InterventionClass, Confidence],
) -> InterventionCandidate:
    """Return a copy of *candidate* upgraded with an LLM *verdict* (pure).

    The upgraded row clears ``needs_llm`` and keeps the raw text in ``notes``
    so a re-label is always possible even after an LLM assignment.
    """
    klass, conf = verdict
    return replace(
        candidate,
        intervention_class=klass,
        confidence=conf,
        needs_llm=False,
    )
