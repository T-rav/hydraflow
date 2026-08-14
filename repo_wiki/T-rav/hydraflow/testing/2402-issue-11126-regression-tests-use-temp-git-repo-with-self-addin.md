---
id: 2402
topic: testing
source_issue: 11126
source_phase: plan
created_at: 2026-08-14T11:53:15.166065+00:00
status: active
corroborations: 1
---

# Regression tests use temp git repo with self-adding fix commit

Regression tests for self-encoded escapes use a temp git repo whose fix commit adds its own `tests/regressions/` pin — no mocked `_run_git`.

- Example: `tests/regressions/test_issue_11126.py` verifies commit `87f0e4466466` added `tests/regressions/test_issue_10393.py` in this repo.
- Scenario tests in `tests/scenarios/` use `FakeGitHub` only — no `subprocess`/`gh`; issue reads stay on `PRPort`.

**Why:** Mocking git would hide real encoding-detection logic; the temp repo exercises the actual `regression_hits` path end-to-end.
