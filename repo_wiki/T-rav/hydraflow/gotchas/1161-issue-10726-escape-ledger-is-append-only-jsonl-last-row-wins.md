---
id: 1161
topic: gotchas
source_issue: 10726
source_phase: plan
created_at: 2026-07-27T18:34:31.163857+00:00
status: active
corroborations: 1
---

# Escape ledger is append-only JSONL, last-row-wins

Resolution rows append a new JSONL line to the escape ledger; never rewrite or delete prior lines. `_reconcile_surfaced_issues` reads the last row for a given escape key to determine current state. **Why:** Rewriting prior lines corrupts the audit trail and breaks reconciliation's last-row-wins semantics, which depend on chronological append to track state transitions.
