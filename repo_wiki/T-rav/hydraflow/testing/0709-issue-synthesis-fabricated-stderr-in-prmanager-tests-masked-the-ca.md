---
id: 0709
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.889284+00:00
status: superseded
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
superseded_by: 0712
---

# Fabricated stderr in PRManager tests masked the cannot/can-not bug

Source fixture strings from actual `gh` CLI output verbatim in `PRManager` tests, rather than fabricating the expected error string.

Example: `tests/test_pr_manager_core.py::test_submit_review_raises_self_review_error_on_approve_own_pr` fed a fabricated `"Cannot approve your own pull request"` stderr, which passed even though production code and real GitHub CLI output disagreed; fixed by using the actual `"Review Can not approve your own pull request (addPullRequestReview)"` string.

**Why:** unit tests that fabricate the external error string instead of copying it verbatim can pass while the real integration is broken — for CLI/API wrapper code (`PRManager`), source fixture strings from actual tool output.
