---
id: 2341
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.078718+00:00
status: active
corroborations: 1
supersedes: 2196
---

# FakeGitHub keys list_runs_for_workflow on display name

`FakeGitHub.list_runs_for_workflow` matches on workflow display name; PRManager's takes a workflow filename. A scenario that passes against the fake can fail live.

Example: add a public display-name→workflow-file resolver beside `_load_workflow_job_timeouts` in `gate_health_loop.py` that scans `.github/workflows/` at runtime. In the scenario, exercise both the resolver and `list_runs_for_workflow` against the same fixture.

**Why:** Divergent identity semantics let a regression sail through the scenario layer and surface only on a live tick.
