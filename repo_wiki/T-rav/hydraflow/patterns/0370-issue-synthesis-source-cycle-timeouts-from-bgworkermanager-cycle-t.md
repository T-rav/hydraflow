---
id: 0370
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:10:17.167705+00:00
status: superseded
corroborations: 1
supersedes: 0356,0357,0358,0359,0360,0361,0362,0363
superseded_by: 0373
---

# Source cycle timeouts from BGWorkerManager.cycle_timeout, not new config

When a detector or loop needs a worker's max expected cycle duration, call `BGWorkerManager.cycle_timeout(worker)` — the same accessor `HealthMonitorLoop` already uses, which honors per-worker overrides and bespoke `timeout_cb` loops. Guard access the same way `get_interval` is guarded (hasattr check), falling back to `cfg.loop_watchdog_default_seconds` when `bg_workers` is absent.

Example from `src/trust_fleet_sanity_loop.py` (~L275-293): `max_cycle_s = int(bg.cycle_timeout(worker)) if bg and hasattr(bg, "cycle_timeout") else cfg.loop_watchdog_default_seconds`.

**Why:** avoids introducing a duplicate/new config field for data the watchdog contract already exposes, keeping ADR-0045 trust-loop changes minimal and additive.
