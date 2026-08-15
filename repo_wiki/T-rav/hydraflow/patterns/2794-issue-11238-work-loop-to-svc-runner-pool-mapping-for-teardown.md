---
id: 2794
topic: patterns
source_issue: 11238
source_phase: plan
created_at: 2026-08-15T09:37:15.548534+00:00
status: active
corroborations: 1
---

# Work-loop to _svc runner-pool mapping for teardown

Work loops map to `_svc` runner pools: plan→planners, implement→agents, review→reviewers, hitl→hitl_runner. `reap_all_tracked_processes()` runs only on the all-pools path.

**Why:** Pool-scoped teardown must terminate only pools owned by the paused provider's classified loops; mis-targeting kills pools for loops that should keep running.
