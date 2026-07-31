---
id: 1548
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:30:39.174087+00:00
status: active
corroborations: 1
supersedes: 1464
---

# FakeGitHub tracks workflow display name and file name separately

Use `workflow=` for the display name and `workflow_file=` for the file name in `FakeGitHub.add_workflow_run`. `list_runs_for_workflow` must match on `workflow_file` with a fallback to `workflow` for legacy seeds.

Example: `add_workflow_run(workflow="RC Promotion Scenario", workflow_file="rc-promotion-scenario.yml")`

**Why:** GitHub's `list_workflow_runs` projects `.name` while `list_runs_for_workflow` keys on the file name; blending them creates latent traps for blame-correlation consumers.
