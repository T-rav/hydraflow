---
id: 0309
topic: gotchas
source_issue: 10258
source_phase: plan
created_at: 2026-07-22T09:21:49.448755+00:00
status: superseded
corroborations: 1
superseded_by: 0310
---

# Browser Scenarios timeout guard added alongside rc_budget fix in same PR

PR #10256 bundled two related-but-distinct fixes: the `rc_budget_loop` cancelled-run misclassification and a timeout guard for `tests/scenarios/browser/workflows/test_orchestrator_controls.py`, with regression coverage in `tests/regressions/test_scenario_browser_timeout_guard_10215.py`. Both tracked under the same issue (#10215) despite touching different subsystems.

**Why:** when auditing #10215/#10256 history, expect two independent fix areas (rc_budget dedup logic and Browser Scenarios timeout handling) rather than a single-cause bug.
