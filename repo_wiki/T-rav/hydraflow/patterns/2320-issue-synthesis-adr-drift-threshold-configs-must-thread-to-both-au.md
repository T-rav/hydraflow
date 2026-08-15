---
id: 2320
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T05:19:55.596728+00:00
status: active
corroborations: 1
supersedes: 2200
---

# ADR-drift threshold configs must thread to both auditor call sites

Any new config-driven threshold in `src/adr_touchpoint_auditor_loop.py` must be passed to both the main scan (`partition_fleet_drift`, ~L699) and stale-rollup reconcile (`compute_drift_by_adr`, ~L580).

Example: Pass the same `shared_infra_fanout_threshold` value into both call sites. See also: [patterns] — adr_drift nudge fan-out: filter before counting.

**Why:** Rollups self-close only when a reconcile pass recomputes empty — if reconcile doesn't receive the same threshold, a fan-out-suppressed rollup strands open forever.
