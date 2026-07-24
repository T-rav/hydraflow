---
id: 0619
topic: testing
source_issue: 10309
source_phase: plan
created_at: 2026-07-24T04:15:22.309952+00:00
status: superseded
corroborations: 1
superseded_by: 0632
---

# In-process MockWorld harness can't run pipeline + loops together — use sandbox for that

The in-process test harness runs `run_pipeline` XOR `run_with_loops`, never both in one call. A scenario that needs both the standard `hydraflow-ready` pipeline *and* `StagingPromotionLoop` running concurrently (e.g. `s82_post_merge_full_machine`) must set `IN_PROCESS=False` so it runs against the real sandbox instead.
**Why:** Scenarios exercising cross-loop interaction silently can't be expressed via the faster in-process harness — picking `IN_PROCESS=True` here would just never invoke one of the two loops.
