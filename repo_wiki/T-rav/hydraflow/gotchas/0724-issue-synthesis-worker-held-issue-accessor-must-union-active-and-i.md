---
id: 0724
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:18:53.819637+00:00
status: superseded
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
superseded_by: 0763
---

# Worker-held issue accessor must union active and in-flight sets

Provide a worker-held accessor on `IssueStore` (src/issue_store.py) that unions `_active` ∪ `_in_flight`, not `_active` alone.

Example: the dequeue→mark_active window means an issue can be claimed by a worker but not yet in `_active` — it's tracked in `_in_flight` during that gap; checking `_active` alone misses issues mid-pickup and flips an epic to `queued` instead of `running` for a brief window.

**Why:** Narrow state checks that ignore transitional/in-flight windows produce flaky, timing-dependent classification bugs.
