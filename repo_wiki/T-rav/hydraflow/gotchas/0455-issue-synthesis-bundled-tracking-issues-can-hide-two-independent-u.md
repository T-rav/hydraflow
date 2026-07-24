---
id: 0455
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:27:31.385100+00:00
status: superseded
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
superseded_by: 0494
---

# Bundled tracking issues can hide two independent, unverified fixes

A single tracking issue can bundle unrelated fixes in one PR — don't assume a single root cause when auditing history.

Example: PR #10256 bundled the `rc_budget_loop` cancelled-run misclassification fix with an unrelated timeout guard for `tests/scenarios/browser/workflows/test_orchestrator_controls.py`, both tracked under issue #10215, with regression coverage in `tests/regressions/test_scenario_browser_timeout_guard_10215.py`.

**Why:** Treating a bundled PR as one fix causes an auditor to miss that one of the two subsystems (rc_budget dedup logic vs. Browser Scenarios timeout handling) was never actually verified.
