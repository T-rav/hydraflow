---
id: 0750
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.463974+00:00
status: superseded
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
superseded_by: 0754
---

# Keep src/adr_drift.py pure; inject state via params, don't cross-import

`src/adr_drift.py` must stay a pure module — no direct imports of state accessors like `_SHARED_INFRA_MODULES` from other modules. Instead, thread new inputs (e.g. `shared_infra: frozenset[str] | None = None`) as parameters through `compute_drift`, `compute_drift_by_adr`, and `partition_fleet_drift`, defaulting to the static set for backward compatibility.

Example: loops (`adr_touchpoint_auditor_loop.py`) compute the effective value once per tick and pass it in.

**Why:** keeps `adr_drift.py` unit-testable without state/DB fixtures and preserves the P2 gate's existing behavior for callers that don't pass the new param.
