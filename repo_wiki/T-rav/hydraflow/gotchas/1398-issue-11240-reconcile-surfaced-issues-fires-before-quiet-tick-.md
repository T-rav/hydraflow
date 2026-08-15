---
id: 1398
topic: gotchas
source_issue: 11240
source_phase: plan
created_at: 2026-08-15T09:55:52.986972+00:00
status: active
corroborations: 1
---

# _reconcile_surfaced_issues fires before quiet-tick early exit

When reasoning about `EscapeLedgerLoop` tick behavior, note that `_reconcile_surfaced_issues` (in `src/escape_ledger_loop.py`, before `_resolve_range`'s quiet-tick early exit at ~line 382) runs unconditionally — open-link diagnosis fires even with no new commits.
- A large OPEN backlog re-diagnoses in full every tick unless explicitly bounded.
- Each diagnose call costs 2 git subprocesses + 1 `PRPort.get_issue_labels`.

**Why:** Assuming reconcile is gated by new commits leads to unbounded subprocess load on idle repos with stale open links.
