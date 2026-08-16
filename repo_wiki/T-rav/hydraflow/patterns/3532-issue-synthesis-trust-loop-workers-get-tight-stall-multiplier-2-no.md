---
id: 3532
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T12:13:22.455840+00:00
status: active
corroborations: 1
supersedes: 3385
---

# Trust-loop workers get tight stall multiplier (2), not blanket 3

`_worker_stall_multiplier` in `src/health_monitor_loop.py` must return the tight multiplier (2) for any `TRUST_LOOP_WORKERS` member; the blanket multiplier (3) is reserved for non-trust registry loops like `workspace_gc`.

Example: Union `TRUST_LOOP_WORKERS` with `cfg.worker_stall_tight_loops` (escape hatch only); `worker_stall_tight_loops` default emptied to `[]` — one source of truth. See also: [patterns] — Fix stall sweep bounds at config.

**Why:** A blanket 3× multiplier leaves a residual alert→remediation gap up to ~7d for weekly trust loops; the tight multiplier bounds it to `min(2×interval, cycle_timeout)` (≤2h).
