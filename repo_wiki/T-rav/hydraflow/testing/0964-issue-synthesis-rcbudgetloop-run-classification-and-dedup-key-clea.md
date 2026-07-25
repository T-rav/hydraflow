---
id: 0964
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.552037+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
---

# RcBudgetLoop run classification and dedup-key clearing test together

Test _fetch_recent_runs (src/rc_budget_loop.py) run-status classification alongside dedup-key clearing for rc_budget:{kind} keys, not in isolation.

Example: see tests/regressions/test_rc_budget_cancelled_run_misclassification_10215.py and tests/test_rc_budget_loop.py, covering a cancelled-run classification fix that required clearing dedup keys as one change.

**Why:** A run-status filtering fix that doesn't also clear stale rc_budget:{kind} dedup keys leaves the loop skipping reprocessing of runs it just reclassified (PR #10256, Fixes #10215).
