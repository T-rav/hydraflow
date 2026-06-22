---
id: 0021
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.694669+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Use `log_exception_with_bug_classification()` to separate bugs from transient errors

Use `log_exception_with_bug_classification()` or `is_likely_bug()` to distinguish bug exceptions (TypeError, AttributeError, KeyError) from transient errors (OSError, network errors).

Example: in `finally` blocks use `log_exception_with_bug_classification(exc)` rather than `reraise`, to preserve finally semantics while still classifying.

**Why:** Logging all exceptions as bugs floods Sentry with transient noise; wrong classification makes signal-to-noise ratio useless.
