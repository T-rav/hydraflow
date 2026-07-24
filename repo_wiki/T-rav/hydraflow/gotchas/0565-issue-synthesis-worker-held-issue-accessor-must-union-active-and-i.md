---
id: 0565
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:39:28.193122+00:00
status: superseded
corroborations: 1
supersedes: 0494,0495,0496,0497,0498,0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539
superseded_by: 0593
---

# Worker-held issue accessor must union active and in-flight sets

Provide a worker-held accessor on `IssueStore` (src/issue_store.py) that unions `_active` ∪ `_in_flight`, not `_active` alone.

Example: the dequeue→mark_active window means an issue can be claimed by a worker but not yet in `_active` — it's tracked in `_in_flight` during that gap; checking `_active` alone misses issues mid-pickup and flips an epic to `queued` instead of `running` for a brief window.

**Why:** Narrow state checks that ignore transitional/in-flight windows produce flaky, timing-dependent classification bugs.
