---
id: 0976
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T04:11:10.509123+00:00
status: superseded
corroborations: 1
supersedes: 0912
superseded_by: 1043
---

# Config field naming mirrors sibling fields for discoverability

New `adr_drift_*` config fields in `src/config.py` should mirror the naming shape of existing sibling fields rather than inventing new conventions.

Example: `adr_drift_shared_infra_fanout_threshold` mirrors `adr_drift_fleet_batch_threshold`, keeping the `adr_drift_<concern>_threshold` pattern and its matching `_ENV_INT_OVERRIDES` env var (`HYDRAFLOW_ADR_DRIFT_SHARED_INFRA_FANOUT_THRESHOLD`).

**Why:** Consistent naming lets future readers grep `adr_drift_` in `src/config.py` and immediately infer the env override name without checking `_ENV_INT_OVERRIDES`.
