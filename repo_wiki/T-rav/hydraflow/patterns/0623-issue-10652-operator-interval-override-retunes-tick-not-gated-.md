---
id: 0623
topic: patterns
source_issue: 10652
source_phase: plan
created_at: 2026-07-26T16:08:03.465335+00:00
status: superseded
corroborations: 1
superseded_by: 0665
---

# Operator interval override retunes tick, not gated heavy pass

When `BGWorkerManager.set_interval("health_monitor", …)` stretches the effective tick beyond `health_monitor_interval`, the heavy-pass gate must use `max(health_monitor_interval, effective_tick)` so a stretched override still yields one heavy pass per tick.

- Gate condition: `elapsed >= max(health_monitor_interval, effective_tick)`
- Prevents zero heavy passes when operator override > 2h

**Why:** Gating only on `health_monitor_interval` silently disables heavy checks when an operator stretches the tick interval.
