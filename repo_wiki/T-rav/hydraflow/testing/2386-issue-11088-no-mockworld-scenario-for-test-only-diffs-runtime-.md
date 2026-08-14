---
id: 2386
topic: testing
source_issue: 11088
source_phase: plan
created_at: 2026-08-14T08:31:19.200158+00:00
status: superseded
corroborations: 1
superseded_by: 2574
---

# No MockWorld scenario for test-only diffs; runtime path already covered

Do not add a `tests/scenarios/` or `tests/sandbox_scenarios/` scenario for a test-only diff when the runtime path is already exercised by an existing scenario.

- `script_plan_credit_exhaustion` is driven by `tests/sandbox_scenarios/scenarios/s89_credit_pause_auto_resume.py` via `MockWorldSeed.credit_exhaustion` → `sandbox_main.build_services`.
- Test-only changes (no `src/` delta) get behavioral tests in the existing fake-test file, not new scenarios.

**Why:** Avoids redundant scenario-tier coverage that adds maintenance cost without exercising new orchestrator/runner/Port behavior.
