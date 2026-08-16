---
id: 2696
topic: testing
source_issue: 11321
source_phase: plan
created_at: 2026-08-16T09:00:03.766498+00:00
status: active
corroborations: 1
---

# MockWorld short-circuits DiagnosticRunner Stage 1 before spawn

Do not add `tests/scenarios/` tests for `DiagnosticRunner` Stage-1 command shape.

`_mockworld_diagnosis` short-circuits before spawn under the fake LLM (sandbox s05). Pin command shape via `tests/test_diagnostic_runner.py` and `tests/regressions/` unit + regression tests instead.

**Why:** Scenario tests cannot observe the spawn and would silently pass regardless of tool flags.
