---
id: 1480
topic: gotchas
source_issue: 11414
source_phase: plan
created_at: 2026-08-18T03:10:06.299878+00:00
status: active
corroborations: 1
---

# Source-shape tripwire tests catch silent reducer reset-site drift

Rule: After fixing a multi-site invariant violation in `HydraFlowContext.jsx`, add a source-shape tripwire test asserting the pattern `pipelineIssues: { ...emptyPipeline }` appears in reducer source only within `initialState` and `clearedPipeline()`.

Example: In `__tests__/railResyncInvariant.test.jsx`, assert that a fourth reset site bypassing the helper fails the build.

**Why:** Behavioral tests pin known sites but cannot prevent a new developer from adding a fifth `...state` spread that re-introduces the same clock-skew bug — a structural assertion catches it at CI time.
