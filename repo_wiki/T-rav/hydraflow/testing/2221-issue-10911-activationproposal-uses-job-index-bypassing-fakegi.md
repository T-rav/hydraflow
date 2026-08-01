---
id: 2221
topic: testing
source_issue: 10911
source_phase: plan
created_at: 2026-07-31T13:18:17.706667+00:00
status: superseded
corroborations: 1
superseded_by: 2363
---

# ActivationProposal uses job_index, bypassing FakeGitHub

Do not fix `workflow=` values in `tests/scenarios/test_gate_activator_scenario.py` using FakeGitHub rules. `workflow="ci.yml"` in this suite maps to `ActivationProposal` and `job_index` pairs in `scripts/gates/workflow_jobs.py`.

**Why:** The `job_index` pairs `(workflow_filename, job_key)` directly; routing this through FakeGitHub's display-name slot is a misattribution that breaks gate activation logic.
