---
id: "01KY4QJX17AGZK48K8ZSR9VWJX"
name: "EscalationReconciler"
kind: "service"
bounded_context: "caretaker"
code_anchor: "src/escalation_reconcile.py:EscalationReconciler"
aliases: ["escalation lifecycle reconciler", "hitl escalation reconciler"]
related: [{"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9B6"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9B5"}, {"kind": "depends_on", "target": "01KRBL0F20M01PGF32CF88W9B2"}, {"kind": "depends_on", "target": "01KR9A3F20M01PGF32CF88W9A4"}, {"kind": "depends_on", "target": "01KR9A3F20M01PGF32CF88W9A1"}, {"kind": "depends_on", "target": "01KT3WKPR5MN8QJ14CF77W6K6"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K7"}, {"kind": "depends_on", "target": "01KY4QF8BE4Y5782543MPQNDQ0"}]
evidence: ["01KQP0V9KK99G77287P414NFRG"]
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-22T10:57:46.023398+00:00"
updated_at: "2026-07-22T16:41:56.908667+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-07-22T10:57:46.023345+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 6
---

## Definition

EscalationReconciler is the shared reconciliation service that closes the loop on hitl-escalation lifecycle state for trust/caretaker loops. It resolves two lifecycle paths every adopting loop needs: reconcile_closed drops the dedup key and attempt counter when a human/external actor closes an escalation issue (re-arming the detector), while reconcile_open auto-closes an open escalation whose subject is no longer present in the loop's currently-detected set (the gap was fixed or was a false positive), clearing its dedup/attempt state so a genuine recurrence escalates fresh. It encodes the bot-vs-human close distinction via the shared BOT_CLOSE_MARKER_LABEL/is_bot_close predicate so a programmatic close never prematurely re-arms a still-active subject.

## Invariants

- reconcile_open only proceeds when the tick's detection completed (active_subjects is not None) — closing on incomplete/partial scan data would kill real escalations and reset their attempt budgets.
- A bot/programmatic close (marked with BOT_CLOSE_MARKER_LABEL before closing) retains the dedup key so a still-detected subject does not immediately refile a duplicate; only a human/external close resets dedup state.
- Unparseable escalation titles (operator-created issues carrying the stuck label) are left untouched by subject_from_title returning None.
