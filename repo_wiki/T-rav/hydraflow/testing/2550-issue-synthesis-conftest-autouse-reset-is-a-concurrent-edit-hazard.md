---
id: 2550
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.307315+00:00
status: active
corroborations: 1
supersedes: 2361
---

# Conftest autouse reset is a concurrent-edit hazard

`tests/conftest.py::_reset_gh_semaphore` (autouse, function-scoped) is the single fixture that clears all `subprocess_util` module globals. When multiple issues touch module-global state, extend it in place — never add a second parallel breaker/semaphore fixture.

**Why:** Parallel fixtures race on teardown order and one silently overwrites the other's reset, re-introducing the exact state leak the fixture was meant to fix.
