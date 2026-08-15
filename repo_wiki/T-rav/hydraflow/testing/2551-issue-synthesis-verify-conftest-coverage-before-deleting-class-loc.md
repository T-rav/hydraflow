---
id: 2551
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.311963+00:00
status: active
corroborations: 1
supersedes: 2362
---

# Verify conftest coverage before deleting class-local fixtures

Before deleting a class-local `_reset_state` fixture (e.g. `tests/test_subprocess_util.py:1036`, `:1187`), grep for every global name it assigns and confirm `tests/conftest.py::_reset_gh_semaphore` clears the same set — including `_gh_semaphore` and `_rate_limit_until`, not just the breaker.

**Why:** A class-local fixture that clears multiple globals will cause test failures from an uncleared semaphore or rate-limit window, not from the breaker you intended to fix — and the failure looks unrelated to your change.
