---
id: 3414
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T08:05:57.912085+00:00
status: superseded
corroborations: 1
supersedes: 3277
superseded_by: 3561
---

# Cost-per-call denominator must exclude usage_unavailable_calls

In `src/prompt_efficiency.py`, compute `billed_calls = inference_calls − usage_unavailable_calls` and divide cost by that — in both window and baseline halves. Fall back to `inference_calls` when the result is ≤ 0 to avoid divide-by-zero.

Example: On #11085's real totals (29 calls / $73.94 / 3 unavailable) the trend stays above threshold. See also: [patterns] — Compare window-to-window, not window-vs-lifetime.

**Why:** Including unavailable-usage calls in the denominator underreports cost-per-call and can mask real regressions as noise.
