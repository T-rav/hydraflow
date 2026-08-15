---
id: 2634
topic: testing
source_issue: 11217
source_phase: plan
created_at: 2026-08-15T06:04:15.266853+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Push-seam tests must drive real git in a tmp repo, not mocks

For `push_branch` guard tests in `tests/test_pr_manager*.py`, create a real temporary git repo and exercise the `[gone]`-upstream condition against it.

A mocked push proves nothing — the guard reads actual `git for-each-ref` output, so the test must produce real ref state. First-push, live-branch, and failing-ref-scan cases should also be unflagged against real refs.

**Why:** Mocking the git layer bypasses the exact parsing logic the guard depends on, producing tests that pass while the guard fails on real repositories.
