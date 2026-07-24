---
id: 0791
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:12:20.365743+00:00
status: active
corroborations: 1
supersedes: 0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753
---

# Fabricated stderr in PRManager tests masked the cannot/can-not bug

Source fixture strings from actual `gh` CLI output verbatim in `PRManager` tests, rather than fabricating the expected error string.

Example: `tests/test_pr_manager_core.py::test_submit_review_raises_self_review_error_on_approve_own_pr` fed a fabricated `"Cannot approve your own pull request"` stderr, which passed even though production code and real GitHub CLI output disagreed; fixed by using the actual `"Review Can not approve your own pull request (addPullRequestReview)"` string.

**Why:** unit tests that fabricate the external error string instead of copying it verbatim can pass while the real integration is broken — for CLI/API wrapper code (`PRManager`), source fixture strings from actual tool output.
