---
id: 0123
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:37:07.466141+00:00
status: active
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
---

# Use `log_exception_with_bug_classification()` for bugs vs transient

Use `log_exception_with_bug_classification()` or `is_likely_bug()` to distinguish bug exceptions (TypeError, AttributeError, KeyError) from transient errors (OSError, network errors).

Example: in `finally` blocks use `log_exception_with_bug_classification(exc)` rather than `reraise`, to preserve finally semantics while still classifying.

**Why:** Logging all exceptions as bugs floods Sentry with transient noise; wrong classification makes signal-to-noise ratio useless.
