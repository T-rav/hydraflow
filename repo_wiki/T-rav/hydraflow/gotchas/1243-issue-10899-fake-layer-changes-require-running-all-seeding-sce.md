---
id: 1243
topic: gotchas
source_issue: 10899
source_phase: plan
created_at: 2026-07-31T11:25:57.702225+00:00
status: active
corroborations: 1
---

# Fake-layer changes require running all seeding scenarios, not a subset

Changes to `FakeGitHub` have a wider blast radius than the diff suggests. Any modification to `add_workflow_run` or its reads must run every seeding scenario: `test_flake_tracker_scenario`, `test_rc_budget_scenario`, `test_caretaker_loops_part2`, `test_pr_red_repair_scenario`, `test_gate_activator_scenario`, plus regression and contract tests.

- Strict file-name matching can silently empty a read that a scenario depends on.
- Today only display-name seeds exist without file-scoped reads, so breakage is non-obvious.

**Why:** A fake that returns `[]` for a previously-matching query fails silently — scenarios pass with empty caches instead of erroring.
