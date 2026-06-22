---
id: 0022
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.694860+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Use `logger.warning(..., exc_info=True)` for transient errors, not `logger.exception()`

Log transient operational failures with `logger.warning(msg, exc_info=True)`. Reserve `logger.exception()` for genuine bugs.

Example: `except (OSError, httpx.NetworkError) as exc: logger.warning('fetch failed', exc_info=True)`.

**Why:** When migrating from `logger.exception()` to `logger.warning()`, forgetting `exc_info=True` silently drops the traceback, making failures undebuggable in production.
