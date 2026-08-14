---
id: 1302
topic: gotchas
source_issue: 11128
source_phase: plan
created_at: 2026-08-14T12:04:30.040485+00:00
status: active
corroborations: 1
---

# Test layering: real git for regressions, fakes for scenarios

Regression tests under `tests/regressions/` use real temp git repos — do not mock git. Scenario tests under `tests/scenarios/` use `FakeGitHub` / `MockWorld` fakes only — no `subprocess`, no `gh` CLI.

- `tests/regressions/test_issue_11128.py`: real temp repos, reproduces exact production state
- `tests/scenarios/test_escape_ledger_scenario.py`: `FakeGitHub` only

**Why:** Mixing layers hides git-level bugs behind mocks; the regression pin must exercise real `commit_info_for_sha` / `added_paths` behavior.
