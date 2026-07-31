---
id: 2220
topic: testing
source_issue: 10907
source_phase: plan
created_at: 2026-07-31T13:13:56.125109+00:00
status: superseded
corroborations: 1
superseded_by: 2362
---

# Verify conftest coverage before deleting class-local fixtures

Rule: before deleting a class-local `_reset_state` fixture (e.g., `tests/test_subprocess_util.py:1036`, `:1187`), grep for every global name it assigns and confirm `tests/conftest.py::_reset_gh_semaphore` clears the same set — including `_gh_semaphore` and `_rate_limit_until`, not just the breaker.

**Why:** a class-local fixture that clears multiple globals will cause test failures from an uncleared semaphore or rate-limit window, not from the breaker you intended to fix — and the failure looks unrelated to your change.
