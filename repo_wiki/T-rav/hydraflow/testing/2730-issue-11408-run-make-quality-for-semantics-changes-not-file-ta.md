---
id: 2730
topic: testing
source_issue: 11408
source_phase: plan
created_at: 2026-08-18T02:52:22.040883+00:00
status: active
corroborations: 1
---

# Run make quality for semantics changes, not file-targeted subsets

Rule: For cleanup or semantics changes in `src/backlog_budget.py` or similar pure-function engines, run `make quality` (full suite), not a file-targeted pytest subset.

Example: A one-line identity-check swap in `retirement_picks` touched no other file but required the full suite because the blast radius exceeds the diff. `tests/test_backlog_budget.py` must stay green unmodified as the default-path parity check.

**Why:** Semantics changes alter the contract other tests implicitly depend on; file-targeted runs miss cross-module regressions that only surface under the full suite.
