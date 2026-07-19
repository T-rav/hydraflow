---
id: 0158
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:23:52.951139+00:00
status: active
corroborations: 1
supersedes: 0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145
---

# Use `logger.warning(..., exc_info=True)` for transient errors

Log transient operational failures with `logger.warning(msg, exc_info=True)`. Reserve `logger.exception()` for genuine bugs.

Example: `except (OSError, httpx.NetworkError) as exc: logger.warning('fetch failed', exc_info=True)`.

**Why:** When migrating from `logger.exception()` to `logger.warning()`, forgetting `exc_info=True` silently drops the traceback, making failures undebuggable.
