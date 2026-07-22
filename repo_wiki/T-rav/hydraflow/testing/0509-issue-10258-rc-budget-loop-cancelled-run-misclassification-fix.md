---
id: 0509
topic: testing
source_issue: 10258
source_phase: plan
created_at: 2026-07-22T09:21:49.448749+00:00
status: active
corroborations: 1
---

# rc_budget_loop cancelled-run misclassification fix lives in _fetch_recent_runs

`src/rc_budget_loop.py`'s `_fetch_recent_runs` previously misclassified cancelled CI runs, and dedup keys of the form `rc_budget:{kind}` needed clearing as part of the fix (PR #10256, `Fixes #10215`). Regression coverage: `tests/regressions/test_rc_budget_cancelled_run_misclassification_10215.py` and `tests/test_rc_budget_loop.py`.

**Why:** future changes to run-status filtering in `RcBudgetLoop` should check this classification path and its dedup-key interaction, since a fix already had to correct both together.
