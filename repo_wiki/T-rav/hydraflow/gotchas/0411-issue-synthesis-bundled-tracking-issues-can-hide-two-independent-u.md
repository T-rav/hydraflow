---
id: 0411
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:55:43.288617+00:00
status: superseded
corroborations: 1
supersedes: 0370,0371,0372,0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
superseded_by: 0446
---

# Bundled tracking issues can hide two independent, unverified fixes

A single tracking issue can bundle unrelated fixes in one PR — don't assume a single root cause when auditing history.

Example: PR #10256 bundled the `rc_budget_loop` cancelled-run misclassification fix with an unrelated timeout guard for `tests/scenarios/browser/workflows/test_orchestrator_controls.py`, both tracked under issue #10215, with regression coverage in `tests/regressions/test_scenario_browser_timeout_guard_10215.py`.

**Why:** Treating a bundled PR as one fix causes an auditor to miss that one of the two subsystems (rc_budget dedup logic vs. Browser Scenarios timeout handling) was never actually verified.
