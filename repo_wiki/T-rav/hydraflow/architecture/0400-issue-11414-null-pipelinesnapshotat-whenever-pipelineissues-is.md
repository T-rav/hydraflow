---
id: 0400
topic: architecture
source_issue: 11414
source_phase: plan
created_at: 2026-08-18T03:10:06.299848+00:00
status: active
corroborations: 1
---

# Null pipelineSnapshotAt whenever pipelineIssues is emptied in reducer

Rule: Any reducer branch in `HydraFlowContext.jsx` that sets `pipelineIssues` to `{ ...emptyPipeline }` must also null `pipelineSnapshotAt`. Without both keys, `isPipelineResyncing()` returns `false` on a stale timestamp, so `PipelineRail.jsx` omits the "resyncing…" chip and renders confidently-empty after a scope switch.

Example: Use a module-local `clearedPipeline()` helper returning `{ pipelineIssues: { ...emptyPipeline }, pipelineSnapshotAt: null }`; spread it at `SELECT_REPO`, `SESSION_RESET`, and `orchestrator_status` start branches instead of a bare `pipelineIssues` key.

**Why:** A bare `pipelineIssues` key inside a `...state` spread silently inherits the prior scope's timestamp, breaking the freshness-clock invariant that PR #11403 missed.
