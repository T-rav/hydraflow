---
id: 0056
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:16:33.335373+00:00
status: superseded
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
superseded_by: 0078
---

# Use `logger.warning(..., exc_info=True)` for transient errors

Log transient operational failures with `logger.warning(msg, exc_info=True)`. Reserve `logger.exception()` for genuine bugs.

Example: `except (OSError, httpx.NetworkError) as exc: logger.warning('fetch failed', exc_info=True)`.

**Why:** When migrating from `logger.exception()` to `logger.warning()`, forgetting `exc_info=True` silently drops the traceback, making failures undebuggable in production.
