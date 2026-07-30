---
id: 0781
topic: patterns
source_issue: 10801
source_phase: plan
created_at: 2026-07-28T10:16:18.732680+00:00
status: superseded
corroborations: 1
superseded_by: 0837
---

# Trust-loop workers get tight stall multiplier (2), not blanket 3

Rule: `_worker_stall_multiplier` in `src/health_monitor_loop.py` must return the tight multiplier for any `TRUST_LOOP_WORKERS` member, because trust-loop membership is exactly the condition "an earlier competing alert exists." The blanket multiplier (3) is reserved for non-trust registry loops like `workspace_gc`. The tight multiplier (2) is the smallest safe integer because the no-false-restart floor is `interval + cycle_timeout`.

- Union `TRUST_LOOP_WORKERS` with `cfg.worker_stall_tight_loops` (escape hatch only)
- `worker_stall_tight_loops` default emptied to `[]` — one source of truth

**Why:** A blanket 3× multiplier leaves a residual alert→remediation gap up to ~7d for weekly trust loops; the tight multiplier bounds it to `min(2×interval, cycle_timeout)` (≤2h).
