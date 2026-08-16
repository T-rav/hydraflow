---
id: 1466
topic: gotchas
source_issue: 11354
source_phase: plan
created_at: 2026-08-16T15:20:51.560182+00:00
status: active
corroborations: 1
---

# Clear fetchHealth alongside pipelineIssues on SELECT_REPO and SESSION_RESET

When adding new state slices to `HydraFlowContext.jsx` `initialState`, wire them into both reset paths: the `SELECT_REPO` slug-change case and `SESSION_RESET`. `fetchHealth` must be cleared alongside `pipelineIssues` in both.

**Why:** Stale health data from a previous repo slug or session leaks across context resets, showing wrong degradation state for the new context.
