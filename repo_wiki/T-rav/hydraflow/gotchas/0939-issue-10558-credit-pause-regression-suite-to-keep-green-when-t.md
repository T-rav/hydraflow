---
id: 0939
topic: gotchas
source_issue: 10558
source_phase: plan
created_at: 2026-07-25T23:16:50.588377+00:00
status: superseded
corroborations: 1
superseded_by: 0940
---

# Credit-pause regression suite to keep green when touching pause logic

Any change to `_pause_for_credits` or `CreditExhaustedError` must keep these regression tests passing: `test_issue_9807_*`, `test_issue_9888_credit_fp_throttle.py`, `test_issue_9895_diagnostic_credit_prose.py`, `test_issue_9924_credit_false_positive_restart.py`, `test_weekly_limit_credit_pause.py`, `test_session_limit_credit_pause.py`, `test_credit_exhausted_reraise.py`. Run `tests/regressions/test_issue_10558.py` red-first as the pinned spec for the origin discriminator.
**Why:** the credit-pause path has a history of regressions (#9807 provider scoping, #9895/#9924 false-positive pauses) each pinned by a dedicated test; skipping any one risks reintroducing a fixed bug.
