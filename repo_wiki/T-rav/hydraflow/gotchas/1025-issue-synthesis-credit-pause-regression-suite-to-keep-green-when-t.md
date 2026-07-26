---
id: 1025
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:48:37.286659+00:00
status: superseded
corroborations: 1
supersedes: 0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895,0896,0897,0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0932,0933,0934,0935,0936,0937,0938,0939
superseded_by: 1039
---

# Credit-pause regression suite to keep green when touching pause logic

Any change to `_pause_for_credits` or `CreditExhaustedError` must keep these regression tests passing: `test_issue_9807_*`, `test_issue_9888_credit_fp_throttle.py`, `test_issue_9895_diagnostic_credit_prose.py`, `test_issue_9924_credit_false_positive_restart.py`, `test_weekly_limit_credit_pause.py`, `test_session_limit_credit_pause.py`, `test_credit_exhausted_reraise.py`. Run `tests/regressions/test_issue_10558.py` red-first as the pinned spec for the origin discriminator.

**Why:** the credit-pause path has a history of regressions (#9807 provider scoping, #9895/#9924 false-positive pauses) each pinned by a dedicated test; skipping any one risks reintroducing a fixed bug.
