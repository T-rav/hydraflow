"""Pure adjudication reconcile for sampled-audit disagreements (#10370).

A disagreement files a ``hydraflow-find`` issue and takes the standard
adjudication path (fix / refute with evidence / encode the exception). Both
outcomes feed calibration (decided):

* **upheld** → a silent escape found; cross-linked into the escape ledger and
  counted against the gate class it implicates;
* **refuted** → the auditor's false-alarm rate; an auditor that over-fires gets
  its own alarm budget tightened.

``reconcile_disposition`` is the pure mechanical rule mapping a filed find
issue's resolved state + labels to a disposition — mirroring the escape
ledger's mechanical-first attribution. The adjudication actors (a human, or a
downstream fix/close) mark the issue: an ``audit-refuted`` label (or a
not-planned close) means the auditor was wrong; any other closed state means the
disagreement was upheld. An open issue stays ``pending``. Never raises.
"""

from __future__ import annotations

# Label an adjudicator applies to a filed find issue to REFUTE the auditor.
REFUTED_LABEL = "audit-refuted"
# Label an adjudicator applies to a filed find issue to UPHOLD the auditor.
UPHELD_LABEL = "audit-upheld"

# Closed-issue states that gh resolves; a not-planned close reads as a refusal.
_NOT_PLANNED_STATES = ("NOT_PLANNED", "NOT PLANNED", "CLOSED_NOT_PLANNED")


def reconcile_disposition(issue_state: str, labels: list[str]) -> str:
    """Map a find issue's ``(state, labels)`` to ``pending|upheld|refuted``.

    Pure and label-first so it is unit-testable without GitHub. Precedence:
    an explicit ``audit-refuted``/``audit-upheld`` label wins; otherwise a
    not-planned close reads as refuted and any other closed state as upheld;
    an open issue stays pending.
    """
    lowered = {label.lower() for label in labels}
    if REFUTED_LABEL in lowered:
        return "refuted"
    if UPHELD_LABEL in lowered:
        return "upheld"

    state = (issue_state or "").strip().upper().replace("-", "_")
    if state in ("OPEN", ""):
        return "pending"
    if state in _NOT_PLANNED_STATES:
        return "refuted"
    # COMPLETED / CLOSED / MERGED / any other resolved state: the disagreement
    # drove a real change → upheld.
    return "upheld"
