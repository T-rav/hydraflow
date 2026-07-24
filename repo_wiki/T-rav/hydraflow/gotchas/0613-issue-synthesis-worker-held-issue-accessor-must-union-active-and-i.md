---
id: 0613
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:28.235334+00:00
status: superseded
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0643
---

# Worker-held issue accessor must union active and in-flight sets

Provide a worker-held accessor on `IssueStore` (src/issue_store.py) that unions `_active` ∪ `_in_flight`, not `_active` alone.

Example: the dequeue→mark_active window means an issue can be claimed by a worker but not yet in `_active` — it's tracked in `_in_flight` during that gap; checking `_active` alone misses issues mid-pickup and flips an epic to `queued` instead of `running` for a brief window.

**Why:** Narrow state checks that ignore transitional/in-flight windows produce flaky, timing-dependent classification bugs.
