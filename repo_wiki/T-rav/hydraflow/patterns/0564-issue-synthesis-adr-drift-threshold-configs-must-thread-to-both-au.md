---
id: 0564
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:39:17.752603+00:00
status: superseded
corroborations: 1
supersedes: 0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0542,0543,0544,0545,0546,0547,0548,0549
superseded_by: 0598
---

# ADR-drift threshold configs must thread to both auditor call sites

`src/adr_touchpoint_auditor_loop.py` calls drift computation from two places: the main scan (`partition_fleet_drift`, ~L699) and stale-rollup reconcile (`compute_drift_by_adr`, ~L580). Any new config-driven threshold (e.g. `shared_infra_fanout_threshold`) must be passed to both, not just the main scan. See also: patterns — adr_drift nudge fan-out: filter before counting, not just before emitting.

Example: pass the same `shared_infra_fanout_threshold` value into both `partition_fleet_drift` and `compute_drift_by_adr` call sites.

**Why:** rollups self-close only when a reconcile pass recomputes empty — if reconcile doesn't receive the same threshold as the main scan, a fan-out-suppressed rollup strands open forever instead of auto-closing.
