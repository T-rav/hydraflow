---
id: 0290
topic: architecture
source_issue: 10903
source_phase: plan
created_at: 2026-07-31T11:47:02.702102+00:00
status: active
corroborations: 1
---

# Clear telemetry cache via bare `telemetry.spans` alias, not `src.`

Clear telemetry state using the same import alias production uses. In `tests/conftest.py`, import `clear_tracer_cache` from `telemetry.spans` (bare alias) rather than `src.telemetry.spans`. `src.telemetry.spans` and `telemetry.spans` resolve to distinct `sys.modules` objects; clearing one does not clear the other. **Why:** `lru_cache` invalidation fails silently if applied to the wrong module instance, causing stale tracers to persist across tests.
