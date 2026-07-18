---
id: 0055
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T04:11:59.906416+00:00
status: active
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
---

# Use `log_exception_with_bug_classification()` to classify bugs vs transient

Use `log_exception_with_bug_classification()` or `is_likely_bug()` to distinguish bug exceptions (TypeError, AttributeError, KeyError) from transient errors (OSError, network errors).

Example: in `finally` blocks use `log_exception_with_bug_classification(exc)` rather than `reraise`, to preserve finally semantics while still classifying.

See also: gotchas — Use `logger.warning(..., exc_info=True)` for transient, not `logger.exception()`.

**Why:** Logging all exceptions as bugs floods Sentry with transient noise; wrong classification makes signal-to-noise ratio useless.
