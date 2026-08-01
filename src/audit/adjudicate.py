"""Machine auto-adjudication for sampled-audit disagreements (ADR-0115).

Before ``SampledAuditLoop`` leaves a re-audit disagreement for a human
adjudicator, this module runs the move a human used to run by hand (the manual
resolution of #10750 / #10751): re-read the merged diff plus the auditor's
disagreement finding with a FRESH adversarial context and decide whether the
finding is real.

* **upheld** — the auditor found a genuine correctness/safety/spec-fidelity
  problem the gauntlet missed. The disagreement takes the ``audit-upheld`` path
  (crosses into the escape ledger via the existing reconcile), NOT
  ``human-required``.
* **refuted** — the auditor was wrong (a stylistic nit, a misread, or a
  correct-as-merged change). The disagreement takes the ``audit-refuted`` path
  (closed with evidence, counted against the auditor's false-alarm budget).
* **inconclusive** — the adjudicator itself can't tell. ONLY then is the finding
  left unlabelled for a human, exactly as before.

The adjudicator is a real one-shot LLM spawn (like the re-auditor), so the loop
gates it behind BOTH ``sampled_audit_auto_adjudicate_enabled`` and
``sampled_audit_reaudit_enabled`` — the air-gapped sandbox pins the latter OFF,
so no adjudicator ``claude`` is reachable there either. ``parse_adjudication`` is
fail-soft toward ``inconclusive``: a malformed adjudicator response must never
fabricate an ``upheld`` (which cross-links a false escape) or a ``refuted``
(which suppresses a real one) — an unparseable verdict reaches a human.
"""

from __future__ import annotations

import json
from typing import Protocol

from audit.budget import MAX_DIFF_CONTEXT_CHARS
from audit.models import AuditSample

__all__ = [
    "ADJUDICATION_VERDICTS",
    "AdjudicatorLLM",
    "build_adjudication_prompt",
    "parse_adjudication",
]

#: The three verdicts an adjudication can land on. ``inconclusive`` is the
#: fail-soft default (→ human), so it is listed but never inferred from a guess.
ADJUDICATION_VERDICTS: tuple[str, ...] = ("upheld", "refuted", "inconclusive")

_DIFF_CONTEXT_CHARS = MAX_DIFF_CONTEXT_CHARS


class AdjudicatorLLM(Protocol):
    """Minimal one-shot completion seam for the adjudication.

    Tests inject a fake; production lazily builds the CLI client (mirrors
    ``sampled_audit_loop._AuditLLM``).
    """

    async def adjudicate(self, *, prompt: str) -> str: ...


def build_adjudication_prompt(sample: AuditSample, diff: str) -> str:
    """Assemble the adjudication prompt — fresh context, the auditor's finding.

    Unlike the re-audit prompt (which withholds all prior verdicts to keep the
    disagreement rate independent), adjudication is EXPLICITLY the step that
    judges the auditor's claim, so the finding is shown. The adjudicator still
    forms its own view of the diff — it is told to REFUTE the finding as readily
    as uphold it, so a trigger-happy auditor is caught.
    """
    return (
        "Adjudicate a disputed code review: an adversarial re-auditor "
        "re-reviewed an ALREADY-MERGED change and claims it has a "
        "correctness / safety / spec-fidelity problem the original gauntlet "
        "missed. Decide from the diff itself — do NOT defer to the auditor. "
        "Uphold the finding only if the diff really has the problem it names; "
        "refute a stylistic nit, a misread, or a correct-as-merged change.\n\n"
        f"PR: #{sample.pr_number}\n"
        f"Merge SHA: {sample.merge_sha}\n"
        f"Blast-radius class: {sample.blast_radius_class}\n\n"
        "The re-auditor's finding:\n"
        f"{sample.findings or '(none recorded)'}\n\n"
        "Merged diff (truncated):\n"
        f"{diff[:_DIFF_CONTEXT_CHARS]}\n\n"
        'Respond with STRICT JSON: {"verdict": "upheld" | "refuted" | '
        '"inconclusive", "rationale": "<one paragraph>"}. "inconclusive" '
        "routes to a human — use it only when upheld and refuted are both "
        "unsupportable."
    )


def parse_adjudication(raw: str) -> tuple[str, str]:
    """Parse ``(verdict, rationale)`` from the adjudicator's stdout, tolerantly.

    Accepts a bare JSON object or JSON embedded in prose. Any unparseable or
    unrecognized verdict collapses to ``inconclusive`` with the raw text as the
    rationale — the fail-soft direction: a malformed response must reach a human,
    never fabricate an ``upheld`` (a false escape cross-link) or a ``refuted``
    (a suppressed real escape).
    """
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            verdict = str(obj.get("verdict", "inconclusive")).strip().lower()
            rationale = str(obj.get("rationale", "")).strip()
            if verdict in ("upheld", "refuted"):
                return verdict, rationale
            return "inconclusive", rationale
    return "inconclusive", text[:500]
