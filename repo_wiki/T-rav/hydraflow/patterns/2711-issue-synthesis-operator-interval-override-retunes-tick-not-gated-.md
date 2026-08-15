---
id: 2711
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T10:07:01.806278+00:00
status: active
corroborations: 1
supersedes: 2588
---

# Operator interval override retunes tick, not gated heavy pass

When `BGWorkerManager.set_interval("health_monitor", …)` stretches the effective tick beyond `health_monitor_interval`, the heavy-pass gate must use `max(health_monitor_interval, effective_tick)` so a stretched override still yields one heavy pass per tick.

Example: Gate condition: `elapsed >= max(health_monitor_interval, effective_tick)` prevents zero heavy passes when operator override > 2h.

**Why:** Gating only on `health_monitor_interval` silently disables heavy checks when an operator stretches the tick interval.
