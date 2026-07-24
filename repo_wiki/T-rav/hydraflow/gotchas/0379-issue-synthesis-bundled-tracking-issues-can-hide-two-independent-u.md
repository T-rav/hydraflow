---
id: 0379
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:12:12.386131+00:00
status: superseded
corroborations: 1
supersedes: 0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369
superseded_by: 0402
---

# Bundled tracking issues can hide two independent, unverified fixes

A single tracking issue can bundle unrelated fixes in one PR — don't assume a single root cause when auditing history.

Example: PR #10256 bundled the `rc_budget_loop` cancelled-run misclassification fix with an unrelated timeout guard for `tests/scenarios/browser/workflows/test_orchestrator_controls.py`, both tracked under issue #10215, with regression coverage in `tests/regressions/test_scenario_browser_timeout_guard_10215.py`.

**Why:** Treating a bundled PR as one fix causes an auditor to miss that one of the two subsystems (rc_budget dedup logic vs. Browser Scenarios timeout handling) was never actually verified.
