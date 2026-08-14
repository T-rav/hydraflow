---
id: 1320
topic: gotchas
source_issue: 11145
source_phase: plan
created_at: 2026-08-14T15:10:07.166495+00:00
status: active
corroborations: 1
---

# trust_fleet_sanity_loop has a local gh reconcile query, not escalation_reconcile

Unlike most caretaker loops that reconcile escalations via the shared `escalation_reconcile` helper on their `-stuck` sub-label, `trust_fleet_sanity_loop.py` runs its own closed-escalation `gh` query that filters directly on the escalation label literal.

- When migrating labels, this loop's reconcile query must be updated alongside its writer — not just the filing call.
- Flipping only the writer wedges dedup so the detector never re-fires.
- Expect a merge conflict with #11139 which is in flight on the same file.

**Why:** A loop-local query that hardcodes the label bypasses the union-read fix, silently breaking closed-issue reconciliation for that one loop.
