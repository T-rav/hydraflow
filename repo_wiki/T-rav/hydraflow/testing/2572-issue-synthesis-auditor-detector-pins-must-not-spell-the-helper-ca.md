---
id: 2572
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.664576+00:00
status: active
corroborations: 1
supersedes: 2384
---

# Auditor detector pins must not spell the helper call literal

When writing a regression pin that reruns `FakeCoverageAuditorLoop._grep_scenario_for_helper` over `tests/`, never write the literal `<helper>(` text in the pin file — derive helper names from `catalog_fake_methods` at runtime.

Example: Bad: `rg -F "script_plan_credit_exhaustion("` in the pin source. Good: iterate `catalog_fake_methods()['FakeLLM']['test-helper']` and grep for `f"{name}("`.

**Why:** The detector greps for the literal call text anywhere under `tests/`, so a pin that spells it satisfies itself and masks real coverage gaps.
