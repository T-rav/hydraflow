---
id: 0316
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T12:09:59.037407+00:00
status: superseded
corroborations: 1
supersedes: 0302,0303,0304,0305,0306,0307,0308,0309
superseded_by: 0317
---

# Expect two independent fix areas when auditing issue #10215/#10256

A single tracking issue can bundle unrelated fixes in one PR — don't assume a single root cause when auditing history.

Example: PR #10256 bundled the `rc_budget_loop` cancelled-run misclassification fix with an unrelated timeout guard for `tests/scenarios/browser/workflows/test_orchestrator_controls.py`, both tracked under issue #10215, with regression coverage in `tests/regressions/test_scenario_browser_timeout_guard_10215.py`.

**Why:** Treating a bundled PR as one fix causes an auditor to miss that one of the two subsystems (rc_budget dedup logic vs. Browser Scenarios timeout handling) was never actually verified.
