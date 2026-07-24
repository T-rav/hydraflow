---
id: 0896
topic: testing
source_issue: 10486
source_phase: review
created_at: 2026-07-24T22:14:13.479975+00:00
status: active
corroborations: 1
---

# Bug-guard assertions belong only in tests/regressions/, not duplicated in unit tests

When adding a `tests/regressions/test_*_<issue>.py` file, don't also add the same assertions to the existing unit test for that code path. In #10486, `tests/test_unpushed_branch_alert.py` and `tests/regressions/test_unpushed_branch_alert_banner_message_10486.py` both ended up asserting `message` non-empty, branch name present, and `severity == "warning"` for the same fixture — the unit test's new block was redundant since the regression test already guards the bug.

**Why:** `tests/regressions/` is the established home for bug-guard assertions; duplicating them in the unit test adds maintenance surface with no added coverage.
