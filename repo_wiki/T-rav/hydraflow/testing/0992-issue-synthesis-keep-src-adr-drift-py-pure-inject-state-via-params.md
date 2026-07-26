---
id: 0992
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.586819+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
---

# Keep src/adr_drift.py pure; inject state via params, don't cross-import

src/adr_drift.py must stay a pure module — no direct imports of state accessors like _SHARED_INFRA_MODULES from other modules. Instead, thread new inputs (e.g. shared_infra: frozenset[str] | None = None) as parameters through compute_drift, compute_drift_by_adr, and partition_fleet_drift, defaulting to the static set for backward compatibility.

Example: loops (adr_touchpoint_auditor_loop.py) compute the effective value once per tick and pass it in.

**Why:** keeps adr_drift.py unit-testable without state/DB fixtures and preserves the P2 gate's existing behavior for callers that don't pass the new param.
