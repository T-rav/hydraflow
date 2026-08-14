---
id: 1555
topic: patterns
source_issue: 11085
source_phase: plan
created_at: 2026-08-14T05:58:31.318359+00:00
status: superseded
corroborations: 1
superseded_by: 1640
---

# Cost-per-call denominator must exclude usage_unavailable_calls

In `src/prompt_efficiency.py`, compute `billed_calls = inference_calls − usage_unavailable_calls` and divide cost by that — in both window and baseline halves. Fall back to `inference_calls` when the result is ≤ 0 to avoid divide-by-zero.

- On #11085's real totals (29 calls / $73.94 / 3 unavailable) the trend stays above threshold.
- An anomaly-only swing (denominator artifact) reports zero trend and files nothing.

**Why:** Including unavailable-usage calls in the denominator underreports cost-per-call and can mask real regressions as noise.
