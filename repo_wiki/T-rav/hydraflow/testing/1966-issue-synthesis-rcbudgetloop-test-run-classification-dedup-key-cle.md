---
id: 1966
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:52.840142+00:00
status: superseded
corroborations: 1
supersedes: 1839
superseded_by: 2096
---

# RcBudgetLoop: test run classification + dedup-key clearing

Test _fetch_recent_runs (src/rc_budget_loop.py) run-status classification alongside dedup-key clearing for rc_budget:{kind} keys, not in isolation.

Example: see tests/regressions/test_rc_budget_cancelled_run_misclassification_10215.py and tests/test_rc_budget_loop.py.

**Why:** A run-status filtering fix that doesn't also clear stale rc_budget:{kind} dedup keys leaves the loop skipping reprocessing of reclassified runs (PR #10256, Fixes #10215).
