---
id: 2720
topic: testing
source_issue: 11343
source_phase: plan
created_at: 2026-08-16T13:08:39.701158+00:00
status: active
corroborations: 1
---

# tests/scenarios/ files require -m scenario_loops marker

Scenario test files under `tests/scenarios/` are gated behind the `scenario_loops` pytest marker. Running a file directly without `-m scenario_loops` deselects every test silently.

```
# Correct:
pytest tests/scenarios/test_label_drift_watcher_scenario.py -m scenario_loops
# Wrong (runs zero tests, exits 0):
pytest tests/scenarios/test_label_drift_watcher_scenario.py
```

**Why:** Without the marker, pytest reports success with zero collection — a false green that hides broken or unrun scenario coverage.
