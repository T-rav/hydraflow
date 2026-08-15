---
id: 2797
topic: patterns
source_issue: 11240
source_phase: plan
created_at: 2026-08-15T09:55:52.986965+00:00
status: superseded
corroborations: 1
superseded_by: 2924
---

# Count only actual diagnose() calls, not positions, in cap enforcement

When enforcing `escape_ledger_max_diagnoses_per_tick` in `_diagnose_open_links`, decrement the budget only for real `EscapeAutoDiagnoser.diagnose()` invocations — terminal/duplicate skips are free.
- INCONCLUSIVE writes no sidecar row, so `terminal_ids()` never short-circuits an unresolved surface — these re-diagnose every tick.
- Counting positions means a backlog of already-adjudicated rows consumes budget before live ones.

**Why:** Counting positions starves live surfaces behind a sea of already-terminal ones, defeating the cap's purpose.
