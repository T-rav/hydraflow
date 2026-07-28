---
id: 0838
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T12:54:49.541328+00:00
status: active
corroborations: 1
supersedes: 0783
---

# Fix stall sweep bounds at config, not shared comparison operators

When fixing boundary conditions in `HealthMonitorLoop` stall sweeps, modify the config field bounds (e.g., `worker_stall_tight_multiplier` `ge=2` in `src/config.py`) rather than relaxing the comparison operator.

- The `elapsed_s < threshold_s` comparison is shared with the blanket-multiplier path and the `loop-stalled` auto-close recovery branch.
- Changing it to `<=` shifts the boundary for every registry loop.

**Why:** Relaxing shared comparison operators silently widens the blast radius to unrelated loop recovery paths.
