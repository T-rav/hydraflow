---
id: 0749
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.452333+00:00
status: active
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
---

# Fabricated stderr in PRManager tests masked the cannot/can-not bug

Source fixture strings from actual `gh` CLI output verbatim in `PRManager` tests, rather than fabricating the expected error string.

Example: `tests/test_pr_manager_core.py::test_submit_review_raises_self_review_error_on_approve_own_pr` fed a fabricated `"Cannot approve your own pull request"` stderr, which passed even though production code and real GitHub CLI output disagreed; fixed by using the actual `"Review Can not approve your own pull request (addPullRequestReview)"` string.

**Why:** unit tests that fabricate the external error string instead of copying it verbatim can pass while the real integration is broken — for CLI/API wrapper code (`PRManager`), source fixture strings from actual tool output.
