---
id: 1053
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.517211+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# Keep src/adr_drift.py pure; inject state via params, don't cross-import

src/adr_drift.py must stay a pure module — no direct imports of state accessors like _SHARED_INFRA_MODULES from other modules. Instead, thread new inputs (e.g. shared_infra: frozenset[str] | None = None) as parameters through compute_drift, compute_drift_by_adr, and partition_fleet_drift, defaulting to the static set for backward compatibility.

Example: loops (adr_touchpoint_auditor_loop.py) compute the effective value once per tick and pass it in.

**Why:** keeps adr_drift.py unit-testable without state/DB fixtures and preserves the P2 gate's existing behavior for callers that don't pass the new param.
