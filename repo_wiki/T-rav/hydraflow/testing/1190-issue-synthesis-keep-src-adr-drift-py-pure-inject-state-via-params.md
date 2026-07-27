---
id: 1190
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T18:41:12.885916+00:00
status: superseded
corroborations: 1
supersedes: 1121
superseded_by: 1264
---

# Keep src/adr_drift.py pure; inject state via params

src/adr_drift.py must stay a pure module — no direct imports of state accessors like _SHARED_INFRA_MODULES from other modules. Instead, thread new inputs as parameters through compute_drift, compute_drift_by_adr, and partition_fleet_drift.

Example: `shared_infra: frozenset[str] | None = None` parameter, defaulting to the static set for backward compatibility; loops compute the effective value once per tick.

**Why:** Keeps adr_drift.py unit-testable without state/DB fixtures and preserves the P2 gate's existing behavior for callers that don't pass the new param.
