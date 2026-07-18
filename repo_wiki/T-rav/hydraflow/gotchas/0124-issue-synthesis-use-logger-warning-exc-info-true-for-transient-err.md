---
id: 0124
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:54:44.600969+00:00
status: active
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
---

# Use `logger.warning(..., exc_info=True)` for transient errors

Log transient operational failures with `logger.warning(msg, exc_info=True)`. Reserve `logger.exception()` for genuine bugs.

Example: `except (OSError, httpx.NetworkError) as exc: logger.warning('fetch failed', exc_info=True)`.

**Why:** When migrating from `logger.exception()` to `logger.warning()`, forgetting `exc_info=True` silently drops the traceback, making failures undebuggable.
