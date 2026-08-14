---
id: 2384
topic: testing
source_issue: 11088
source_phase: plan
created_at: 2026-08-14T08:31:19.200085+00:00
status: superseded
corroborations: 1
superseded_by: 2572
---

# Auditor detector pins must not spell the helper call literal

When writing a regression pin that reruns `FakeCoverageAuditorLoop._grep_scenario_for_helper` (from `src/fake_coverage_auditor_loop.py`) over `tests/`, never write the literal `<helper>(` text in the pin file — derive helper names from `catalog_fake_methods` at runtime.

- Bad: `rg -F "script_plan_credit_exhaustion("` in the pin source.
- Good: iterate `catalog_fake_methods()['FakeLLM']['test-helper']` and grep for `f"{name}("`.

**Why:** The detector greps for the literal call text anywhere under `tests/`, so a pin that spells it satisfies itself and masks real coverage gaps.
