---
id: 1379
topic: gotchas
source_issue: 11217
source_phase: plan
created_at: 2026-08-15T06:04:15.266863+00:00
status: active
corroborations: 1
---

# Caretaker loop dedup keyed on <pr>:<tip_sha> for idempotent re-ticking

Caretaker loops like `OrphanBranchLoop` should dedup filings on `<pr>:<tip_sha>` so that re-ticking with no change files nothing, while a new tip sha on the same PR files again.

- Still-deleted branch → nothing
- Unchanged tip → nothing
- New tip → new issue
- Open PR → nothing

One issue per (merged PR, branch tip) is the invariant.

**Why:** Without a composite dedup key, either re-ticks spam duplicate issues or legitimate new-tip orphans get suppressed.
