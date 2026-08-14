---
id: 0330
topic: architecture
source_issue: 11165
source_phase: plan
created_at: 2026-08-14T19:36:20.069043+00:00
status: active
corroborations: 1
---

# Canonical label imports must be module-level for rename-resilience tests

Import canonical labels at module level, never inside a function body or via config lookup, when a test simulates a rename by reloading the module.

- `src/dashboard_routes/_trust_routes.py` must use `from trust_fleet_anomaly_detectors import HITL_QUEUE_LABEL` at the top, not a function-local import.
- A function-local import or `config.get()` lookup makes `test_fleet_route_queue_label_follows_a_rename` pass for the wrong reason — the reload never touches the binding.

**Why:** Burying the import hides real reader/writer label drift, the exact failure class the canonical-home pattern exists to prevent.
