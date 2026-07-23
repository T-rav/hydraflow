---
id: 0346
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T17:02:49.508781+00:00
status: superseded
corroborations: 1
supersedes: 0327,0328,0329,0330,0331,0332,0333,0334,0335,0336
superseded_by: 0348
---

# Bundled tracking issues can hide two independent, unverified fixes

A single tracking issue can bundle unrelated fixes in one PR — don't assume a single root cause when auditing history.

Example: PR #10256 bundled the `rc_budget_loop` cancelled-run misclassification fix with an unrelated timeout guard for `tests/scenarios/browser/workflows/test_orchestrator_controls.py`, both tracked under issue #10215, with regression coverage in `tests/regressions/test_scenario_browser_timeout_guard_10215.py`.

**Why:** Treating a bundled PR as one fix causes an auditor to miss that one of the two subsystems (rc_budget dedup logic vs. Browser Scenarios timeout handling) was never actually verified.
