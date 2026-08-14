---
id: 2406
topic: testing
source_issue: 11133
source_phase: plan
created_at: 2026-08-14T12:41:23.460429+00:00
status: active
corroborations: 1
---

# Regression tests in tests/regressions/ are immutable contracts

`tests/regressions/test_issue_11133.py` is committed as-is and encodes the acceptance contract — do not weaken its assertions. When a regression test offers multiple remedy branches, the implementation takes one branch and confirms the test passes unmodified.

Run sibling regression pins (e.g. `test_issue_11089.py`, `test_issue_11093.py`) to check whether they close as side effects, and report explicitly in the PR.

**Why:** Weakening a regression test to make it pass defeats its purpose as a permanent guard against the original defect.
