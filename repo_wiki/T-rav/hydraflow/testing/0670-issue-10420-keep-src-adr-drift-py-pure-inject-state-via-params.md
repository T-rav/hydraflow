---
id: 0670
topic: testing
source_issue: 10420
source_phase: plan
created_at: 2026-07-24T06:29:23.521318+00:00
status: active
corroborations: 1
---

# Keep src/adr_drift.py pure; inject state via params, don't cross-import

`src/adr_drift.py` must stay a pure module — no direct imports of state accessors like `_SHARED_INFRA_MODULES` from other modules. Instead, thread new inputs (e.g. `shared_infra: frozenset[str] | None = None`) as parameters through `compute_drift`, `compute_drift_by_adr`, and `partition_fleet_drift`, defaulting to the static set for backward compatibility. Loops (`adr_touchpoint_auditor_loop.py`) compute the effective value once per tick and pass it in.

**Why:** keeps `adr_drift.py` unit-testable without state/DB fixtures and preserves the P2 gate's existing behavior for callers that don't pass the new param.
