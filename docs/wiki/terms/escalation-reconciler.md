---
id: "01KXSK51VJVC32VNEB36YVYFSP"
name: "EscalationReconciler"
kind: "service"
bounded_context: "caretaker"
code_anchor: "src/escalation_reconcile.py:EscalationReconciler"
aliases: ["escalation reconciliation service", "stale escalation closer"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-18T03:08:39.154740+00:00"
updated_at: "2026-07-18T03:08:39.154742+00:00"
proposed_by: "TermProposerLoop"
proposed_at: "2026-07-18T03:08:39.154663+00:00"
proposal_signals: ["S2"]
proposal_imports_seen: 4
---

## Definition

Shared service that reconciles HITL escalation issues for trust loops. Handles two lifecycle paths: closed escalations (a human closed the issue → drop the dedup key and reset the attempt counter so the detector may re-fire) and open escalations (the gap is no longer detected at HEAD — fixed by a later PR or was a false positive → auto-close with an explanatory comment and clear state). Previously copy-pasted as `_reconcile_closed_escalations` across five loops; centralized to eliminate drift and to add the open-escalation path that prevented dead-letter issues from sitting unattended (#9618 sat six days). Each trust loop supplies its own `subject_from_title` parser so subjects are recovered from issue titles, never from dedup keys.

## Invariants

- reconcile_open skips entirely when active_subjects is None (failed or partial detection) — closing on incomplete data would kill real escalations and reset their attempt budgets
- Close-then-clear: dedup key and attempt counter reset only after a successful issue close, persisted per subject; a failed close leaves that subject's state for the next tick
- Port errors propagate without broad excepts — the caller's cycle handler owns error classification per the reraise_on_credit_or_bug rule
