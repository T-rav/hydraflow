---
id: 0390
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:12:12.394926+00:00
status: superseded
corroborations: 1
supersedes: 0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369
superseded_by: 0402
---

# Worker-held issue accessor must union active and in-flight sets

Provide a worker-held accessor on `IssueStore` (src/issue_store.py) that unions `_active` ∪ `_in_flight`, not `_active` alone.

Example: the dequeue→mark_active window means an issue can be claimed by a worker but not yet in `_active` — it's tracked in `_in_flight` during that gap; checking `_active` alone misses issues mid-pickup and flips an epic to `queued` instead of `running` for a brief window.

**Why:** Narrow state checks that ignore transitional/in-flight windows produce flaky, timing-dependent classification bugs.
