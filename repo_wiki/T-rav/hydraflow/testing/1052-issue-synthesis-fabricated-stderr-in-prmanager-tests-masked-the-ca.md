---
id: 1052
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.515623+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# Fabricated stderr in PRManager tests masked the cannot/can-not bug

Source fixture strings from actual gh CLI output verbatim in PRManager tests, rather than fabricating the expected error string.

Example: tests/test_pr_manager_core.py::test_submit_review_raises_self_review_error_on_approve_own_pr fed a fabricated "Cannot approve your own pull request" stderr, which passed even though production code and real GitHub CLI output disagreed; fixed by using the actual "Review Can not approve your own pull request (addPullRequestReview)" string.

**Why:** unit tests that fabricate the external error string instead of copying it verbatim can pass while the real integration is broken — for CLI/API wrapper code (PRManager), source fixture strings from actual tool output.
