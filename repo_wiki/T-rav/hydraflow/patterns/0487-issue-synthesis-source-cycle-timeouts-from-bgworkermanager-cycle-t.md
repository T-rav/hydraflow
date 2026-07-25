---
id: 0487
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T01:09:57.505103+00:00
status: active
corroborations: 1
supersedes: 0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480
---

# Source cycle timeouts from BGWorkerManager.cycle_timeout, not new config

When a detector or loop needs a worker's max expected cycle duration, call `BGWorkerManager.cycle_timeout(worker)` — the same accessor `HealthMonitorLoop` uses — guarded the same way `get_interval` is (hasattr check), falling back to `cfg.loop_watchdog_default_seconds` when `bg_workers` is absent.

Example: in `src/trust_fleet_sanity_loop.py` (~L275-293): `max_cycle_s = int(bg.cycle_timeout(worker)) if bg and hasattr(bg, "cycle_timeout") else cfg.loop_watchdog_default_seconds`.

**Why:** avoids introducing a duplicate/new config field for data the watchdog contract already exposes, keeping ADR-0045 trust-loop changes minimal and additive.
