---
id: 2650
topic: testing
source_issue: 11246
source_phase: plan
created_at: 2026-08-15T20:20:19.664586+00:00
status: active
corroborations: 1
---

# Test FakeGitHub consumer seams with real fake as _pr_manager

For consumer-level tests of loops that call `PRManager`, wire a real `FakeGitHub` instance as the loop's `_pr_manager` (it already satisfies the `_repo`, `_run_gh`, `add_labels` interface) rather than building a bespoke mock.

Extend the existing `_make_loop` pattern in tests/test_report_issue_loop.py with a populated-stub variant that seeds issues via `add_issue`/`add_seeded_comment`.

**Why:** Testing through the real fake exercises the loop↔fake integration seam and catches shape drift that a hand-rolled mock would hide.
