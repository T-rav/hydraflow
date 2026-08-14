---
id: 1734
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T11:12:32.486291+00:00
status: active
corroborations: 1
supersedes: 1640
---

# Cost-per-call denominator must exclude usage_unavailable_calls

In `src/prompt_efficiency.py`, compute `billed_calls = inference_calls − usage_unavailable_calls` and divide cost by that — in both window and baseline halves. Fall back to `inference_calls` when the result is ≤ 0 to avoid divide-by-zero.

Example: On #11085's real totals (29 calls / $73.94 / 3 unavailable) the trend stays above threshold. An anomaly-only swing (denominator artifact) reports zero trend and files nothing.

**Why:** Including unavailable-usage calls in the denominator underreports cost-per-call and can mask real regressions as noise.
