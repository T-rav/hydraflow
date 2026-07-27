---
id: 1173
topic: gotchas
source_issue: 10747
source_phase: plan
created_at: 2026-07-27T22:30:25.835026+00:00
status: active
corroborations: 1
---

# Regression tests parse and execute the finding's printed remediation

`tests/regressions/test_issue_10747.py` extracts the command from the rendered finding body (filling `<...>` placeholders), executes it through the real CLI, and checks the next reconcile closes the issue. The test fails only while the printed command cannot answer its own surfacing.

- Keep the `<a|b|c>` placeholder convention or the parser mis-fires.

**Why:** Testing the fix directly couples the regression to the implementation; testing the printed command couples it to the operator contract.
