---
id: 0922
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T22:10:19.615061+00:00
status: active
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
---

# In-process MockWorld harness can't run pipeline + loops together

The in-process test harness runs `run_pipeline` XOR `run_with_loops`, never both in one call. A scenario that needs both the standard `hydraflow-ready` pipeline *and* `StagingPromotionLoop` running concurrently (e.g. `s82_post_merge_full_machine`) must set `IN_PROCESS=False` so it runs against the real sandbox instead.

**Why:** scenarios exercising cross-loop interaction silently can't be expressed via the faster in-process harness — picking `IN_PROCESS=True` here would just never invoke one of the two loops.
