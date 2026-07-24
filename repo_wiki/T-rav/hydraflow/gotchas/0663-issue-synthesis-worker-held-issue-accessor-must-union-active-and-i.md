---
id: 0663
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.457326+00:00
status: superseded
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
superseded_by: 0704
---

# Worker-held issue accessor must union active and in-flight sets

Provide a worker-held accessor on `IssueStore` (src/issue_store.py) that unions `_active` ∪ `_in_flight`, not `_active` alone.

Example: the dequeue→mark_active window means an issue can be claimed by a worker but not yet in `_active` — it's tracked in `_in_flight` during that gap; checking `_active` alone misses issues mid-pickup and flips an epic to `queued` instead of `running` for a brief window.

**Why:** Narrow state checks that ignore transitional/in-flight windows produce flaky, timing-dependent classification bugs.
