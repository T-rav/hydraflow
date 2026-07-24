---
id: 0477
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:15:19.416880+00:00
status: superseded
corroborations: 1
supersedes: 0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462
superseded_by: 0481
---

# ADR-drift threshold configs must thread to both auditor call sites

`src/adr_touchpoint_auditor_loop.py` calls drift computation from two places: the main scan (`partition_fleet_drift`, ~L699) and stale-rollup reconcile (`compute_drift_by_adr`, ~L580). Any new config-driven threshold (e.g. `shared_infra_fanout_threshold`) must be passed to both, not just the main scan.

Example: pass the same `shared_infra_fanout_threshold` value into both `partition_fleet_drift` and `compute_drift_by_adr` call sites.

**Why:** rollups self-close only when a reconcile pass recomputes empty — if reconcile doesn't receive the same threshold as the main scan, a fan-out-suppressed rollup strands open forever instead of auto-closing.
