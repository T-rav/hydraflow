---
id: 2552
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.316777+00:00
status: active
corroborations: 1
supersedes: 2363
---

# ActivationProposal uses job_index, bypassing FakeGitHub

Do not fix `workflow=` values in `tests/scenarios/test_gate_activator_scenario.py` using FakeGitHub rules. `workflow="ci.yml"` in this suite maps to `ActivationProposal` and `job_index` pairs in `scripts/gates/workflow_jobs.py`.

**Why:** The `job_index` pairs `(workflow_filename, job_key)` directly; routing this through FakeGitHub's display-name slot is a misattribution that breaks gate activation logic.
