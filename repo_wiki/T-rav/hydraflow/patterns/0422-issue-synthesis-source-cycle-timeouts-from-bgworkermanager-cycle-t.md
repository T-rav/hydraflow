---
id: 0422
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:37:01.323610+00:00
status: superseded
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415
superseded_by: 0432
---

# Source cycle timeouts from BGWorkerManager.cycle_timeout, not new config

When a detector or loop needs a worker's max expected cycle duration, call `BGWorkerManager.cycle_timeout(worker)` — the same accessor `HealthMonitorLoop` uses, honoring per-worker overrides and bespoke `timeout_cb` loops — guarded the same way `get_interval` is (hasattr check), falling back to `cfg.loop_watchdog_default_seconds` when `bg_workers` is absent. Example: in `src/trust_fleet_sanity_loop.py` (~L275-293): `max_cycle_s = int(bg.cycle_timeout(worker)) if bg and hasattr(bg, "cycle_timeout") else cfg.loop_watchdog_default_seconds`. **Why:** avoids introducing a duplicate/new config field for data the watchdog contract already exposes, keeping ADR-0045 trust-loop changes minimal and additive.
