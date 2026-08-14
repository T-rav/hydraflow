---
id: 2587
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.899345+00:00
status: active
corroborations: 1
supersedes: 2402
---

# Regression tests use temp git repo with self-adding fix commit

Regression tests for self-encoded escapes use a temp git repo whose fix commit adds its own `tests/regressions/` pin — no mocked `_run_git`.

Example: `tests/regressions/test_issue_11126.py` verifies commit `87f0e4466466` added `tests/regressions/test_issue_10393.py` in this repo. Scenario tests in `tests/scenarios/` use `FakeGitHub` only — no `subprocess`/`gh`; issue reads stay on `PRPort`.

**Why:** Mocking git would hide real encoding-detection logic; the temp repo exercises the actual `regression_hits` path end-to-end.
