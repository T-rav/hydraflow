---
id: 0824
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:43:21.199802+00:00
status: active
corroborations: 1
supersedes: 0754,0755,0756,0757,0758,0759,0760,0761,0762,0763,0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797
---

# In-process MockWorld harness can't run pipeline + loops together

The in-process test harness runs `run_pipeline` XOR `run_with_loops`, never both in one call. A scenario that needs both the standard `hydraflow-ready` pipeline *and* `StagingPromotionLoop` running concurrently (e.g. `s82_post_merge_full_machine`) must set `IN_PROCESS=False` so it runs against the real sandbox instead.

**Why:** scenarios exercising cross-loop interaction silently can't be expressed via the faster in-process harness — picking `IN_PROCESS=True` here would just never invoke one of the two loops.
