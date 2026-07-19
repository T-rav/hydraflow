---
id: 0191
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.154196+00:00
status: superseded
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
superseded_by: 0214
---

# Use `log_exception_with_bug_classification()` for bugs vs transient

Use `log_exception_with_bug_classification()` or `is_likely_bug()` to distinguish bug exceptions from transient errors.

Example: in `finally` blocks use `log_exception_with_bug_classification(exc)` rather than `reraise`, to preserve finally semantics while still classifying.

**Why:** Logging all exceptions as bugs floods Sentry with transient noise; wrong classification makes signal-to-noise ratio useless.
