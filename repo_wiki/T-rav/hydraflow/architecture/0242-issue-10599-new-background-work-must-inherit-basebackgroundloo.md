---
id: 0242
topic: architecture
source_issue: 10599
source_phase: plan
created_at: 2026-07-26T11:44:58.431645+00:00
status: active
corroborations: 1
---

# New background work must inherit BaseBackgroundLoop, not asyncio.Task

Any new periodic worker must subclass `BaseBackgroundLoop`. A plain `asyncio.Task` is invisible: no ADR-0049 kill-switch, no watchdog, no dashboard toggle, and it fails the four CI-enforced wiring sites.

Required wiring: `ServiceRegistry` field, orchestrator `bg_loop_registry` + `loop_factories` + `set_bg_workers()` injection, `constants.js` `BACKGROUND_WORKERS` entry, and `dashboard_routes/_common.py` `_INTERVAL_BOUNDS`.

**Why:** Un-toggleable background work cannot be killed in incidents or surfaced in the operations dashboard.
