---
id: 0738
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.330611+00:00
status: active
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
---

# In-process MockWorld harness can't run pipeline + loops together

The in-process test harness runs `run_pipeline` XOR `run_with_loops`, never both in one call. A scenario that needs both the standard `hydraflow-ready` pipeline *and* `StagingPromotionLoop` running concurrently (e.g. `s82_post_merge_full_machine`) must set `IN_PROCESS=False` so it runs against the real sandbox instead.

**Why:** scenarios exercising cross-loop interaction silently can't be expressed via the faster in-process harness — picking `IN_PROCESS=True` here would just never invoke one of the two loops.
