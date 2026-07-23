---
id: 0362
topic: patterns
source_issue: 10236
source_phase: plan
created_at: 2026-07-22T17:17:17.227712+00:00
status: active
corroborations: 1
---

# Source cycle timeouts from BGWorkerManager.cycle_timeout, not new config

When a detector or loop needs a worker's max expected cycle duration, call `BGWorkerManager.cycle_timeout(worker)` — the same accessor `HealthMonitorLoop` already uses, which honors per-worker overrides and bespoke `timeout_cb` loops. Guard access the same way `get_interval` is guarded (hasattr check), falling back to `cfg.loop_watchdog_default_seconds` when `bg_workers` is absent.

Example from `src/trust_fleet_sanity_loop.py` (~L275-293):
```python
max_cycle_s = int(bg.cycle_timeout(worker)) if bg and hasattr(bg, "cycle_timeout") else cfg.loop_watchdog_default_seconds
```
**Why:** avoids introducing a duplicate/new config field for data the watchdog contract already exposes, keeping ADR-0045 trust-loop changes minimal and additive.
