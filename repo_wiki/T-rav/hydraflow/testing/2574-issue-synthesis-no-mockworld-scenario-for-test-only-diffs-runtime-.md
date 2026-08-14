---
id: 2574
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.684632+00:00
status: active
corroborations: 1
supersedes: 2386
---

# No MockWorld scenario for test-only diffs; runtime path covered

Do not add a `tests/scenarios/` or `tests/sandbox_scenarios/` scenario for a test-only diff when the runtime path is already exercised by an existing scenario.

Example: `script_plan_credit_exhaustion` is driven by `tests/sandbox_scenarios/scenarios/s89_credit_pause_auto_resume.py` via `MockWorldSeed.credit_exhaustion` → `sandbox_main.build_services`. Test-only changes get behavioral tests in the existing fake-test file.

**Why:** Avoids redundant scenario-tier coverage that adds maintenance cost without exercising new orchestrator/runner/Port behavior.
