---
id: 2736
topic: testing
source_issue: 11413
source_phase: plan
created_at: 2026-08-18T03:10:14.007966+00:00
status: active
corroborations: 1
---

# Run make quality for scenario_loops tier; default addopts deselects it

Use `make quality` to exercise scenario tests. Bare `pytest tests/scenarios/` misses the `scenario_loops` tier because default `addopts` deselects it.

- `TestL23cBranchGC` and `TestL23bRegressionRot` in `tests/scenarios/test_caretaker_loops_part2.py` live in the `scenario_loops` marker tier.
- A bare pytest run would silently skip them, repeating the #11395 evidence error where a mock-based scenario hid a fidelity gap.

**Why:** Skipping the tier means the only tests that exercise `FakeGitHub` against real loop logic never run, making regressions invisible.
