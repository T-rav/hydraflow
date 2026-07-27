---
id: 1263
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T20:11:03.201735+00:00
status: active
corroborations: 1
supersedes: 1189
---

# Fabricated stderr in PRManager tests masked cannot/can-not bug

Source fixture strings from actual gh CLI output verbatim in PRManager tests, rather than fabricating the expected error string.

Example: tests/test_pr_manager_core.py::test_submit_review_raises_self_review_error_on_approve_own_pr fed fabricated "Cannot approve your own pull request" but real output is "Review Can not approve your own pull request (addPullRequestReview)".

**Why:** Unit tests that fabricate the external error string instead of copying it verbatim can pass while the real integration is broken.
