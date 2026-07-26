---
id: 1123
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:44:02.158781+00:00
status: superseded
corroborations: 1
supersedes: 0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0951,0952,0953,0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014,1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1031,1032,1033,1034,1035,1036
superseded_by: 1144
---

# Credit-pause regression suite to keep green when touching pause logic

Any change to `_pause_for_credits` or `CreditExhaustedError` must keep these regression tests passing: `test_issue_9807_*`, `test_issue_9888_credit_fp_throttle.py`, `test_issue_9895_diagnostic_credit_prose.py`, `test_issue_9924_credit_false_positive_restart.py`, `test_weekly_limit_credit_pause.py`, `test_session_limit_credit_pause.py`, `test_credit_exhausted_reraise.py`. Run `tests/regressions/test_issue_10558.py` red-first as the pinned spec for the origin discriminator.

**Why:** The credit-pause path has a history of regressions each pinned by a dedicated test; skipping any one risks reintroducing a fixed bug.
