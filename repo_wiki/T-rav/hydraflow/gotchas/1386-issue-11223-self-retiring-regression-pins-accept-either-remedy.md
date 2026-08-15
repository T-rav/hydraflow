---
id: 1386
topic: gotchas
source_issue: 11223
source_phase: plan
created_at: 2026-08-15T06:46:05.624562+00:00
status: active
corroborations: 1
---

# Self-retiring regression pins accept either remedy

Regression test files under `tests/regressions/` can mix RED pins (asserting the bug) with GREEN counter-pins (asserting correct behavior) that self-retire when the file is deleted. `tests/regressions/test_issue_11223.py` uses 2 RED + 2 GREEN pins: after the fix, expect 2 passed / 2 skipped / 0 failed. Any failure means the deletion was partial.

**Why:** This pattern lets the test file be deleted wholesale once the issue closes without leaving stale assertions behind.
