---
id: 0734
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T11:16:04.349053+00:00
status: active
corroborations: 1
supersedes: 0677
---

# Source cycle timeouts from BGWorkerManager.cycle_timeout

When a detector or loop needs a worker's max expected cycle duration, call `BGWorkerManager.cycle_timeout(worker)` — guarded the same way `get_interval` is (hasattr check), falling back to `cfg.loop_watchdog_default_seconds` when `bg_workers` is absent.

Example: In `src/trust_fleet_sanity_loop.py` (~L275-293): `max_cycle_s = int(bg.cycle_timeout(worker)) if bg and hasattr(bg, "cycle_timeout") else cfg.loop_watchdog_default_seconds`.

**Why:** Avoids introducing a duplicate config field for data the watchdog contract already exposes, keeping ADR-0045 trust-loop changes minimal and additive.
