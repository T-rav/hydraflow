---
id: 1463
topic: gotchas
source_issue: 11352
source_phase: plan
created_at: 2026-08-16T14:31:03.716400+00:00
status: active
corroborations: 1
---

# Dispatch on fetchPipeline catch to clear in-flight resync flags

`fetchPipeline` in `HydraFlowContext.jsx` currently swallows errors silently in its `.catch`. Any new flag set before the fetch (e.g. `pipelineResyncing: true`) will strand permanently on a 500.

- Add a `PIPELINE_POLL_FAILED` case that clears the in-flight flag but leaves the stale flag set.
- The tripwire can then re-fire on the next cooldown tick rather than hanging.

**Why:** A swallowed error path leaves `resyncing: true` forever, producing a chip that never clears even after the board recovers.
