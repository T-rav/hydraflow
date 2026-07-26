---
id: 0238
topic: architecture
source_issue: 10616
source_phase: plan
created_at: 2026-07-26T11:05:04.471697+00:00
status: active
corroborations: 1
---

# New strategy enums mirror src/queue_strategy.py wiring

When adding a runtime-selectable strategy enum (e.g. `BuildStrategy`), mirror the four-layer wiring of `src/queue_strategy.py`:

- `src/build_strategy.py` — `StrEnum` + helper (e.g. `parallel_waves`)
- `src/config.py` — field + `HYDRAFLOW_*` env var + `_ENV_ENUM_OVERRIDES`
- `src/settings_registry.py` — enum setting row with choices
- `src/dashboard_routes/_control_routes.py` — expose/accept in PATCH

**Why:** Following the established pattern ensures consistent env/config/UI wiring and avoids missing a control-plane layer.
