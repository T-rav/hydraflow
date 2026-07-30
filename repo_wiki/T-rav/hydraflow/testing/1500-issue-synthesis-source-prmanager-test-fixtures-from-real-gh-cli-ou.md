---
id: 1500
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T19:46:33.744702+00:00
status: active
corroborations: 1
supersedes: 1412
---

# Source PRManager test fixtures from real gh CLI output

Source fixture strings from actual gh CLI output verbatim in PRManager tests, rather than fabricating the expected error string.

Example: tests/test_pr_manager_core.py fed fabricated 'Cannot approve your own pull request' but real output is 'Review Can not approve your own pull request (addPullRequestReview)'.

**Why:** Unit tests that fabricate the external error string instead of copying it verbatim can pass while the real integration is broken.
