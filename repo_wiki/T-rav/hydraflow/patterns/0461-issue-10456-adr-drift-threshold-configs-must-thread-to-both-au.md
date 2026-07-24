---
id: 0461
topic: patterns
source_issue: 10456
source_phase: plan
created_at: 2026-07-24T12:31:36.987746+00:00
status: active
corroborations: 1
---

# ADR-drift threshold configs must thread to both auditor call sites

`src/adr_touchpoint_auditor_loop.py` calls drift computation from two places: the main scan (`partition_fleet_drift`, ~L699) and stale-rollup reconcile (`compute_drift_by_adr`, ~L580). Any new config-driven threshold (e.g. `shared_infra_fanout_threshold`) must be passed to both, not just the main scan.

**Why:** [[adr_drift_auditor_autoclose]] documents that rollups self-close only when a reconcile pass recomputes empty — if reconcile doesn't receive the same threshold as the main scan, a fan-out-suppressed rollup strands open forever instead of auto-closing.
