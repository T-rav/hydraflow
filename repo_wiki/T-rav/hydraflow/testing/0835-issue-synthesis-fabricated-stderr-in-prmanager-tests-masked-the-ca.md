---
id: 0835
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:43:21.215491+00:00
status: superseded
corroborations: 1
supersedes: 0754,0755,0756,0757,0758,0759,0760,0761,0762,0763,0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797
superseded_by: 0847
---

# Fabricated stderr in PRManager tests masked the cannot/can-not bug

Source fixture strings from actual `gh` CLI output verbatim in `PRManager` tests, rather than fabricating the expected error string.

Example: `tests/test_pr_manager_core.py::test_submit_review_raises_self_review_error_on_approve_own_pr` fed a fabricated `"Cannot approve your own pull request"` stderr, which passed even though production code and real GitHub CLI output disagreed; fixed by using the actual `"Review Can not approve your own pull request (addPullRequestReview)"` string.

**Why:** unit tests that fabricate the external error string instead of copying it verbatim can pass while the real integration is broken — for CLI/API wrapper code (`PRManager`), source fixture strings from actual tool output.
