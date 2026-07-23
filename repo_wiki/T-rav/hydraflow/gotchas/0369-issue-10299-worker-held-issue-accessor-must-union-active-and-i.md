---
id: 0369
topic: gotchas
source_issue: 10299
source_phase: plan
created_at: 2026-07-22T17:49:09.980190+00:00
status: active
corroborations: 1
---

# Worker-held issue accessor must union active and in-flight sets

The dequeue→mark_active window means an issue can be claimed by a worker but not yet in `_active`; it's tracked in `_in_flight` during that gap. `IssueStore` (src/issue_store.py) needs a public accessor that unions `_active` ∪ `_in_flight` to correctly report an issue as worker-held — using `_active` alone misses issues mid-pickup and would flip an epic to `queued` instead of `running` for a brief window.

**Why:** narrow state checks that ignore transitional/in-flight windows produce flaky, timing-dependent classification bugs.
