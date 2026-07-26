---
id: 0239
topic: architecture
source_issue: 10614
source_phase: plan
created_at: 2026-07-26T11:22:50.702117+00:00
status: active
corroborations: 1
---

# Route PATCH and ConfigReloadLoop through shared config_apply module

Both `_control_routes.py` PATCH handling and `ConfigReloadLoop` must delegate to `src/config_apply.py` rather than reimplementing mutation logic. The apply module: mutates `live` fields in-place, persists `boot` fields without touching live state, and special-cases `gh_circuit_breaker_enabled` to flip the process-global breaker.

**Why:** Divergent apply paths produce round-trip parity breaks where a PATCH works but a reload doesn't (or vice versa).
