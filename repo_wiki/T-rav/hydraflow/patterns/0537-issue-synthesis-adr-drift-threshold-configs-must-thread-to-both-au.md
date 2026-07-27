---
id: 0537
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:44:03.242785+00:00
status: superseded
corroborations: 1
supersedes: 0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522
superseded_by: 0550
---

# ADR-drift threshold configs must thread to both auditor call sites

`src/adr_touchpoint_auditor_loop.py` calls drift computation from two places: the main scan (`partition_fleet_drift`, ~L699) and stale-rollup reconcile (`compute_drift_by_adr`, ~L580). Any new config-driven threshold (e.g. `shared_infra_fanout_threshold`) must be passed to both, not just the main scan. See also: patterns — adr_drift nudge fan-out denominator must filter before counting, not just before emitting.

Example: pass the same `shared_infra_fanout_threshold` value into both `partition_fleet_drift` and `compute_drift_by_adr` call sites.

**Why:** rollups self-close only when a reconcile pass recomputes empty — if reconcile doesn't receive the same threshold as the main scan, a fan-out-suppressed rollup strands open forever instead of auto-closing.
