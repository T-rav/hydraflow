---
id: 3137
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T04:41:05.864079+00:00
status: active
corroborations: 1
supersedes: 3003
---

# FakeGitHub tracks workflow display name and file name separately

Use `workflow=` for the display name and `workflow_file=` for the file name in `FakeGitHub.add_workflow_run`. `list_runs_for_workflow` must match on `workflow_file` with a fallback to `workflow` for legacy seeds.

Example: `add_workflow_run(workflow="RC Promotion Scenario", workflow_file="rc-promotion-scenario.yml")`. See also: [patterns] — Cassette baselines pin projection bytes; [patterns] — list_runs_for_workflow keys on file name.

**Why:** GitHub's `list_workflow_runs` projects `.name` while `list_runs_for_workflow` keys on the file name; blending them creates latent traps for blame-correlation consumers.
