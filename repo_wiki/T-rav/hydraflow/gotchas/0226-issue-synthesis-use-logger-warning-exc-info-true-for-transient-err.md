---
id: 0226
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:45:05.796898+00:00
status: active
corroborations: 1
supersedes: 0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213
---

# Use `logger.warning(..., exc_info=True)` for transient errors

Log transient operational failures with `logger.warning(msg, exc_info=True)`. Reserve `logger.exception()` for genuine bugs.

Example: `except (OSError, httpx.NetworkError) as exc: logger.warning('fetch failed', exc_info=True)`.

**Why:** When migrating from `logger.exception()` to `logger.warning()`, forgetting `exc_info=True` silently drops the traceback, making failures undebuggable.

See also: gotchas — Use `log_exception_with_bug_classification()` for bugs vs transient.
