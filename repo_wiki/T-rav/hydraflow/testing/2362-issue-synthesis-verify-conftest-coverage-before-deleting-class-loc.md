---
id: 2362
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.135793+00:00
status: superseded
corroborations: 1
supersedes: 2220
superseded_by: 2551
---

# Verify conftest coverage before deleting class-local fixtures

Before deleting a class-local `_reset_state` fixture (e.g. `tests/test_subprocess_util.py:1036`, `:1187`), grep for every global name it assigns and confirm `tests/conftest.py::_reset_gh_semaphore` clears the same set — including `_gh_semaphore` and `_rate_limit_until`, not just the breaker.

**Why:** A class-local fixture that clears multiple globals will cause test failures from an uncleared semaphore or rate-limit window, not from the breaker you intended to fix — and the failure looks unrelated to your change.
