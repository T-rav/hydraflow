---
id: 0519
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T12:10:40.691023+00:00
status: superseded
corroborations: 1
supersedes: 0500,0501,0502,0503,0504,0505,0506,0507,0508,0509
superseded_by: 0520
---

# RcBudgetLoop run classification and dedup-key clearing test together

Test `_fetch_recent_runs` (`src/rc_budget_loop.py`) run-status classification alongside dedup-key clearing for `rc_budget:{kind}` keys, not in isolation.

Example: see `tests/regressions/test_rc_budget_cancelled_run_misclassification_10215.py` and `tests/test_rc_budget_loop.py`, covering a cancelled-run classification fix that required clearing dedup keys as one change.

**Why:** A run-status filtering fix that doesn't also clear stale `rc_budget:{kind}` dedup keys leaves the loop skipping reprocessing of runs it just reclassified (PR #10256, Fixes #10215).
