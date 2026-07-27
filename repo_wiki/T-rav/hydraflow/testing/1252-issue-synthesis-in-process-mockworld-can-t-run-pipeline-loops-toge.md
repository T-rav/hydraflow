---
id: 1252
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T20:11:03.090169+00:00
status: superseded
corroborations: 1
supersedes: 1178
superseded_by: 1326
---

# In-process MockWorld can't run pipeline + loops together

The in-process test harness runs run_pipeline XOR run_with_loops, never both in one call.

Example: a scenario needing both the standard pipeline and StagingPromotionLoop running concurrently (e.g. s82_post_merge_full_machine) must set IN_PROCESS=False to run against the real sandbox.

**Why:** Scenarios exercising cross-loop interaction silently can't be expressed via the faster in-process harness — picking IN_PROCESS=True here would just never invoke one of the two loops.
