---
id: 0846
topic: gotchas
source_issue: 10499
source_phase: review
created_at: 2026-07-25T06:08:03.278827+00:00
status: active
corroborations: 1
---

# Regression tests for git-log parsers must drive real git, not mock _run_git

For bugs in `src/escape/detect.py` / `src/audit/detect.py`, write regression tests that shell out to a real `git` binary in a temp repo via `subprocess.run`, not tests that mock the module's internal `_run_git` helper. Confirmed in `tests/regressions/` for issue #10499 (PR #10521). A mocked `_run_git` would have let the original `\x1e` marker bug pass silently, since the mock never exercises real `git log`'s actual output formatting. **Why:** this bug class (sentinel chars colliding with line-termination behavior) only reproduces against real git output — mocking hides exactly the defect the test exists to catch.
