---
id: 1522
topic: gotchas
source_issue: 11501
source_phase: plan
created_at: 2026-08-21T01:19:24.541898+00:00
status: active
corroborations: 1
---

# Pin a liveness counter-test in regression suites

In `tests/regressions/test_issue_*.py`, include a counter-pin that reproduces the original defect scenario *succeeding* (the bare chained recipe that staged 1469 files on the wrong branch). This pin must stay GREEN after the fix.

- It proves the sandbox models the real defect.
- It guards against future test-environment drift that would silently invalidate the other pins.

**Why:** If the liveness pin turns RED, the regression test is no longer exercising the real failure path and all other GREEN pins are false confidence.
