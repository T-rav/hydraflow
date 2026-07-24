---
id: 0669
topic: testing
source_issue: 10413
source_phase: plan
created_at: 2026-07-24T06:07:17.313486+00:00
status: active
corroborations: 1
---

# Fabricated stderr in PRManager tests masked the cannot/can-not bug

`tests/test_pr_manager_core.py::test_submit_review_raises_self_review_error_on_approve_own_pr` fed a fabricated `"Cannot approve your own pull request"` stderr, which passed even though production code and real GitHub CLI output disagreed. Fix: use the actual `"Review Can not approve your own pull request (addPullRequestReview)"` string so the unit test pins the bug.

**Why:** unit tests that fabricate the external error string instead of copying it verbatim can pass while the real integration is broken — for CLI/API wrapper code (`PRManager`), source fixture strings from actual tool output.
