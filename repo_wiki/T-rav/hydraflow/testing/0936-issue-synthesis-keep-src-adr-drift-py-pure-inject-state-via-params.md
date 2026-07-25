---
id: 0936
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:46:40.923084+00:00
status: superseded
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
superseded_by: 0954
---

# Keep src/adr_drift.py pure; inject state via params, don't cross-import

`src/adr_drift.py` must stay a pure module — no direct imports of state accessors like `_SHARED_INFRA_MODULES` from other modules. Instead, thread new inputs (e.g. `shared_infra: frozenset[str] | None = None`) as parameters through `compute_drift`, `compute_drift_by_adr`, and `partition_fleet_drift`, defaulting to the static set for backward compatibility.

Example: loops (`adr_touchpoint_auditor_loop.py`) compute the effective value once per tick and pass it in.

**Why:** keeps `adr_drift.py` unit-testable without state/DB fixtures and preserves the P2 gate's existing behavior for callers that don't pass the new param.
