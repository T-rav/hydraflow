---
id: 0839
topic: gotchas
source_issue: 10503
source_phase: plan
created_at: 2026-07-25T02:16:20.035341+00:00
status: active
corroborations: 1
---

# Write EscapeLedgerLoop surfacing keys only after create_issue succeeds

In `_surface_findings`, mark a reason's dedup key spent only after the corresponding `create_issue` call returns successfully — never before. If the call fails, all keys for that tick stay unspent so the record retries next tick. `CreditExhaustedError` from `create_issue` must still propagate out of `_surface_findings` unchanged (per `reraise_on_credit_or_bug`); don't swallow it while adding the per-reason write logic.

**Why:** Marking keys before the write completes would permanently lose a surfacing on a transient GitHub API failure, since EscapeLedger keys are never retroactively un-spent.
