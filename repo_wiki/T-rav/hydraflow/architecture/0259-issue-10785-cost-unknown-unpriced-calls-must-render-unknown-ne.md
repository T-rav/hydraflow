---
id: 0259
topic: architecture
source_issue: 10785
source_phase: plan
created_at: 2026-07-28T09:16:36.126413+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# cost_unknown/unpriced_calls must render "unknown", never $0.00

Rows with `cost_unknown` or non-zero `unpriced_calls` (introduced by design in #9821) must display as "unknown" in the UI, even when cost is zero.

- A model with `cost_usd=0` and `unpriced_calls>0` is unpriced, not free.
- Only `cost_usd=0` with zero unpriced calls should show `$0.00`.

**Why:** Conflating unpriced calls with zero-cost hides billing gaps and misrepresents spend to operators reviewing the console.
