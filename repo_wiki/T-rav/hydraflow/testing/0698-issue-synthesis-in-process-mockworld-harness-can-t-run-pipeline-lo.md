---
id: 0698
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.871606+00:00
status: active
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
---

# In-process MockWorld harness can't run pipeline + loops together

The in-process test harness runs `run_pipeline` XOR `run_with_loops`, never both in one call. A scenario that needs both the standard `hydraflow-ready` pipeline *and* `StagingPromotionLoop` running concurrently (e.g. `s82_post_merge_full_machine`) must set `IN_PROCESS=False` so it runs against the real sandbox instead.

**Why:** scenarios exercising cross-loop interaction silently can't be expressed via the faster in-process harness — picking `IN_PROCESS=True` here would just never invoke one of the two loops.
