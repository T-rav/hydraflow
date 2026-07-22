---
id: 0530
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T13:39:13.372030+00:00
status: active
corroborations: 1
supersedes: 0510,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519
---

# RcBudgetLoop run classification and dedup-key clearing test together

Test `_fetch_recent_runs` (`src/rc_budget_loop.py`) run-status classification alongside dedup-key clearing for `rc_budget:{kind}` keys, not in isolation.

Example: see `tests/regressions/test_rc_budget_cancelled_run_misclassification_10215.py` and `tests/test_rc_budget_loop.py`, covering a cancelled-run classification fix that required clearing dedup keys as one change.

**Why:** A run-status filtering fix that doesn't also clear stale `rc_budget:{kind}` dedup keys leaves the loop skipping reprocessing of runs it just reclassified (PR #10256, Fixes #10215).
