---
id: 2704
topic: testing
source_issue: 11328
source_phase: plan
created_at: 2026-08-16T09:56:55.839283+00:00
status: active
corroborations: 1
---

# Scenario fold tests use FakeGitHub state, not raw mocks

Write cross-tick fold scenario tests in `tests/scenarios/test_find_class_fold_scenario.py` using `scenario_loops` and real `FakeGitHub` state assertions — no raw mocks.

- Assert on `FakeGitHub`'s issue body and state after each tick rather than patching API calls.
- Regression tests in `tests/regressions/test_issue_11328.py` cover three-tick, closed-issue, and body-token cases.

**Why:** Raw mocks hide lifecycle bugs that surface only when issue state propagates across ticks through the real `PRPort` calls.
