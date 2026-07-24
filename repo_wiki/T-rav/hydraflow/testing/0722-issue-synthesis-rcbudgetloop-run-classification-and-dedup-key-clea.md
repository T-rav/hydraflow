---
id: 0722
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.162513+00:00
status: superseded
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
superseded_by: 0754
---

# RcBudgetLoop run classification and dedup-key clearing test together

Test `_fetch_recent_runs` (`src/rc_budget_loop.py`) run-status classification alongside dedup-key clearing for `rc_budget:{kind}` keys, not in isolation.

Example: see `tests/regressions/test_rc_budget_cancelled_run_misclassification_10215.py` and `tests/test_rc_budget_loop.py`, covering a cancelled-run classification fix that required clearing dedup keys as one change.

**Why:** A run-status filtering fix that doesn't also clear stale `rc_budget:{kind}` dedup keys leaves the loop skipping reprocessing of runs it just reclassified (PR #10256, Fixes #10215).
