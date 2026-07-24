---
id: 0603
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:57:59.578718+00:00
status: superseded
corroborations: 1
supersedes: 0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0632
---

# RcBudgetLoop run classification and dedup-key clearing test together

Test `_fetch_recent_runs` (`src/rc_budget_loop.py`) run-status classification alongside dedup-key clearing for `rc_budget:{kind}` keys, not in isolation.

Example: see `tests/regressions/test_rc_budget_cancelled_run_misclassification_10215.py` and `tests/test_rc_budget_loop.py`, covering a cancelled-run classification fix that required clearing dedup keys as one change.

**Why:** A run-status filtering fix that doesn't also clear stale `rc_budget:{kind}` dedup keys leaves the loop skipping reprocessing of runs it just reclassified (PR #10256, Fixes #10215).
