---
id: 1457
topic: gotchas
source_issue: 11338
source_phase: plan
created_at: 2026-08-16T12:34:38.645188+00:00
status: active
corroborations: 1
---

# Golden scenario artifacts are regenerated, never hand-edited

Regenerate golden JSON via `python scripts/sandbox_scenario.py seed <NAME>`. The output must equal `module.seed().to_json()` or `regression_issue_10094` and the conftest tree-clean guard fail.

Verify with `git status --porcelain tests/sandbox_scenarios/seeds/` — it must be empty after regeneration.

**Why:** Hand-editing goldens produces drift between the seed module and its serialized form; the tree-clean guard and parity test (`tests/scenarios/test_sandbox_parity.py`) are the release-gating checks that catch this.
