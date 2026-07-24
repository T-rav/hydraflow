---
id: 0836
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:43:21.216630+00:00
status: superseded
corroborations: 1
supersedes: 0754,0755,0756,0757,0758,0759,0760,0761,0762,0763,0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797
superseded_by: 0847
---

# Keep src/adr_drift.py pure; inject state via params, don't cross-import

`src/adr_drift.py` must stay a pure module — no direct imports of state accessors like `_SHARED_INFRA_MODULES` from other modules. Instead, thread new inputs (e.g. `shared_infra: frozenset[str] | None = None`) as parameters through `compute_drift`, `compute_drift_by_adr`, and `partition_fleet_drift`, defaulting to the static set for backward compatibility.

Example: loops (`adr_touchpoint_auditor_loop.py`) compute the effective value once per tick and pass it in.

**Why:** keeps `adr_drift.py` unit-testable without state/DB fixtures and preserves the P2 gate's existing behavior for callers that don't pass the new param.
