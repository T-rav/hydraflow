---
id: 2219
topic: testing
source_issue: 10907
source_phase: plan
created_at: 2026-07-31T13:13:56.125099+00:00
status: active
corroborations: 1
---

# Conftest autouse reset is a concurrent-edit hazard

Rule: `tests/conftest.py::_reset_gh_semaphore` (autouse, function-scoped) is the single fixture that clears all `subprocess_util` module globals. When multiple issues touch module-global state (e.g., #10889 and #10907 both edit this fixture and both list `_gh_circuit_breaker`), extend it in place — never add a second parallel breaker/semaphore fixture.

**Why:** parallel fixtures race on teardown order and one silently overwrites the other's reset, re-introducing the exact state leak the fixture was meant to fix.
