---
id: 1763
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T12:50:03.692131+00:00
status: superseded
corroborations: 1
supersedes: 1667
superseded_by: 1861
---

# Config field naming mirrors sibling fields for discoverability

New `adr_drift_*` config fields in `src/config.py` should mirror the naming shape of existing sibling fields rather than inventing new conventions.

Example: `adr_drift_shared_infra_fanout_threshold` mirrors `adr_drift_fleet_batch_threshold`, keeping the `adr_drift_<concern>_threshold` pattern and its matching `_ENV_INT_OVERRIDES` env var (`HYDRAFLOW_ADR_DRIFT_SHARED_INFRA_FANOUT_THRESHOLD`).

**Why:** Consistent naming lets future readers grep `adr_drift_` in `src/config.py` and immediately infer the env override name without checking `_ENV_INT_OVERRIDES`.
