---
id: 1290
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:41:40.071267+00:00
status: active
corroborations: 1
supersedes: 1219
---

# Fix stall sweep bounds at config, not shared comparison operators

When fixing boundary conditions in `HealthMonitorLoop` stall sweeps, modify the config field bounds (e.g. `worker_stall_tight_multiplier` `ge=2` in `src/config.py`) rather than relaxing the comparison operator.

Example: The `elapsed_s < threshold_s` comparison is shared with the blanket-multiplier path and the `loop-stalled` auto-close recovery branch — changing it to `<=` shifts the boundary for every registry loop. See also: patterns — Trust-loop workers get tight stall multiplier.

**Why:** Relaxing shared comparison operators silently widens the blast radius to unrelated loop recovery paths.
