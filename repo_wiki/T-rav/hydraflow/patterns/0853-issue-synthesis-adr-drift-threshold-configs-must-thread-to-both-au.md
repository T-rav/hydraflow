---
id: 0853
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T19:37:32.621435+00:00
status: active
corroborations: 1
supersedes: 0798
---

# ADR-drift threshold configs must thread to both auditor call sites

`src/adr_touchpoint_auditor_loop.py` calls drift computation from two places: the main scan (`partition_fleet_drift`, ~L699) and stale-rollup reconcile (`compute_drift_by_adr`, ~L580). Any new config-driven threshold must be passed to both.

Example: Pass the same `shared_infra_fanout_threshold` value into both `partition_fleet_drift` and `compute_drift_by_adr`. See also: patterns — adr_drift nudge fan-out: filter before counting.

**Why:** Rollups self-close only when a reconcile pass recomputes empty — if reconcile doesn't receive the same threshold, a fan-out-suppressed rollup strands open forever.
