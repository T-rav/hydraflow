---
id: 1942
topic: testing
source_issue: 10881
source_phase: plan
created_at: 2026-07-31T07:22:08.358153+00:00
status: superseded
corroborations: 1
superseded_by: 2067
---

# FakeGitHub keys list_runs_for_workflow on display name; PRManager on filename

Rule: When a `MockWorld` scenario exercises `list_runs_for_workflow`, assert the fake honors the same contract as the live Port. `FakeGitHub.list_runs_for_workflow` matches on the workflow *display name*; `PRManager`'s takes a workflow *filename*. A scenario that passes against the fake can fail live.

Example:
- Add a public display-name→workflow-file resolver beside `_load_workflow_job_timeouts` in `gate_health_loop.py` that scans `.github/workflows/` at runtime (no hardcoded list, no `_`-prefixed cross-module import).
- In the scenario, exercise both the resolver and `list_runs_for_workflow` against the same fixture.

**Why:** Divergent identity semantics let a regression sail through the scenario layer and surface only on a live tick.
