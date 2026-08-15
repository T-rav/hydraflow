---
id: 2299
topic: patterns
source_issue: 11184
source_phase: plan
created_at: 2026-08-14T23:44:16.701404+00:00
status: active
corroborations: 1
---

# Split budget gates: break only for terminal exhaustion, continue for per-item skip

In `AdrDriftResolverLoop._do_work`, use `break` only when no later candidate can fit (`remaining_budget <= 0`); use `continue` when the current batch exceeds budget (`len(adr_numbers) > remaining_budget`) since a later candidate may still fit.

- `src/adr_drift_resolver_loop.py:449` previously broke on both conditions, head-of-line blocking smaller batches behind an oversized one.

**Why:** A `break` on a per-batch fit check starves trailing batches that could have been triaged within the remaining `adr_drift_resolver_max_triage_per_tick` budget.
