---
id: 0710
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.890570+00:00
status: active
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
---

# Keep src/adr_drift.py pure; inject state via params, don't cross-import

`src/adr_drift.py` must stay a pure module — no direct imports of state accessors like `_SHARED_INFRA_MODULES` from other modules. Instead, thread new inputs (e.g. `shared_infra: frozenset[str] | None = None`) as parameters through `compute_drift`, `compute_drift_by_adr`, and `partition_fleet_drift`, defaulting to the static set for backward compatibility.

Example: loops (`adr_touchpoint_auditor_loop.py`) compute the effective value once per tick and pass it in.

**Why:** keeps `adr_drift.py` unit-testable without state/DB fixtures and preserves the P2 gate's existing behavior for callers that don't pass the new param.
