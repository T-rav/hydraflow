---
id: 0089
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:46:56.517330+00:00
status: active
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
---

# Use `log_exception_with_bug_classification()` for bugs vs transient

Use `log_exception_with_bug_classification()` or `is_likely_bug()` to distinguish bug exceptions (TypeError, AttributeError, KeyError) from transient errors (OSError, network errors).

Example: in `finally` blocks use `log_exception_with_bug_classification(exc)` rather than `reraise`, to preserve finally semantics while still classifying.

**Why:** Logging all exceptions as bugs floods Sentry with transient noise; wrong classification makes signal-to-noise ratio useless.
