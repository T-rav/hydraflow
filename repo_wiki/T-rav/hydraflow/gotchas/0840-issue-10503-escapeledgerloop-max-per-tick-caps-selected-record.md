---
id: 0840
topic: gotchas
source_issue: 10503
source_phase: plan
created_at: 2026-07-25T02:16:20.035350+00:00
status: superseded
corroborations: 1
superseded_by: 0851
---

# EscapeLedgerLoop max_per_tick caps selected records, not surfacing reasons

When a record can carry multiple unspent reasons (low-confidence + aging), `max_per_tick` in `select_findings_to_surface` must still count it as one selection toward the cap, not one per reason — otherwise a single dual-reason record could consume two slots of budget for one issue. Test explicitly: 20 eligible rows with `max_per_tick=3` yields exactly 3 selections and `capped is True`.

**Why:** Counting reasons instead of records would make the per-tick issue-filing budget inconsistent with the one-issue-per-record-per-tick invariant the loop otherwise guarantees.
