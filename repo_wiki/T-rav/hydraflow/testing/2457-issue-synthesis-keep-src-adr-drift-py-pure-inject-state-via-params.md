---
id: 2457
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:49.784782+00:00
status: active
corroborations: 1
supersedes: 2267
---

# Keep src/adr_drift.py pure; inject state via params

`src/adr_drift.py` must stay a pure module — no direct imports of state accessors like `_SHARED_INFRA_MODULES` from other modules. Instead, thread new inputs as parameters through `compute_drift`, `compute_drift_by_adr`, and `partition_fleet_drift`.

Example: `shared_infra: frozenset[str] | None = None` parameter, defaulting to the static set for backward compatibility.

**Why:** Keeps `adr_drift.py` unit-testable without state/DB fixtures and preserves the P2 gate's existing behavior for callers that don't pass the new param.
