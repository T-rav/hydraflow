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
downstream fix/close) mark the issue: an ``audit-upheld`` label (or a
not-planned close read as a dismissal) resolves it, an ``audit-refuted`` label
means the auditor was wrong.

**Upheld requires an explicit signal.** An ``upheld`` disposition cross-links a
row into the escape ledger — the instrument's headline "escapes" count — so it
must never be fabricated. A find issue can be closed INCIDENTALLY by an
unrelated loop (stale/dup sweeper) with no adjudication label; defaulting such a
plain close to ``upheld`` would silently inflate the escape count. So only an
explicit ``audit-upheld`` label yields ``upheld``. A closed-but-unlabelled issue
stays ``pending`` (unadjudicated — it inflates neither the escape count nor the
auditor's false-alarm rate, and reconciles once a human applies a label). An
open issue stays ``pending``. Never raises.
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
    not-planned close reads as a dismissal (refuted); an open issue OR a plain
    closed issue with no adjudication label stays ``pending`` — ``upheld``
    (which fabricates an escape-ledger row) is NEVER inferred from a bare close,
    only from the explicit ``audit-upheld`` label, so an incidental stale/dup
    close by another loop cannot inflate the escape count.
    """
    lowered = {label.lower() for label in labels}
    if REFUTED_LABEL in lowered:
        return "refuted"
    if UPHELD_LABEL in lowered:
        return "upheld"

    state = (issue_state or "").strip().upper().replace("-", "_")
    if state in _NOT_PLANNED_STATES:
        return "refuted"
    # OPEN, unresolved, OR a plain close with no adjudication label: NOT enough
    # signal to call it an escape. Stay pending until a human applies an
    # explicit audit-upheld / audit-refuted label. An incidental close must not
    # cross into the escape ledger.
    return "pending"
