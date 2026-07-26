---
id: 0991
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.585557+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
---

# Fabricated stderr in PRManager tests masked the cannot/can-not bug

Source fixture strings from actual gh CLI output verbatim in PRManager tests, rather than fabricating the expected error string.

Example: tests/test_pr_manager_core.py::test_submit_review_raises_self_review_error_on_approve_own_pr fed a fabricated "Cannot approve your own pull request" stderr, which passed even though production code and real GitHub CLI output disagreed; fixed by using the actual "Review Can not approve your own pull request (addPullRequestReview)" string.

**Why:** unit tests that fabricate the external error string instead of copying it verbatim can pass while the real integration is broken — for CLI/API wrapper code (PRManager), source fixture strings from actual tool output.
