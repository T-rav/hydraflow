---
id: 0590
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.333342+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# Source cycle timeouts from BGWorkerManager.cycle_timeout, not new config

When a detector or loop needs a worker's max expected cycle duration, call `BGWorkerManager.cycle_timeout(worker)`, falling back to `cfg.loop_watchdog_default_seconds` when `bg_workers` is absent.

Example: in `src/trust_fleet_sanity_loop.py`: `max_cycle_s = int(bg.cycle_timeout(worker)) if bg and hasattr(bg, "cycle_timeout") else cfg.loop_watchdog_default_seconds`.

**Why:** avoids introducing a duplicate config field for data the watchdog contract already exposes, keeping ADR-0045 changes minimal.
