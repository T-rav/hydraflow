---
id: 0462
topic: patterns
source_issue: 10456
source_phase: plan
created_at: 2026-07-24T12:31:36.987763+00:00
status: superseded
corroborations: 1
superseded_by: 0463
---

# Config field naming mirrors sibling fields for discoverability

New `adr_drift_*` config fields in `src/config.py` should mirror the naming shape of existing sibling fields rather than inventing new conventions. `adr_drift_shared_infra_fanout_threshold` was named to mirror `adr_drift_fleet_batch_threshold`, keeping the `adr_drift_<concern>_threshold` pattern and its matching `_ENV_INT_OVERRIDES` env var (`HYDRAFLOW_ADR_DRIFT_SHARED_INFRA_FANOUT_THRESHOLD`) consistent with existing overrides.

**Why:** consistent naming lets future readers grep `adr_drift_` in `src/config.py` and immediately infer the env override name without checking `_ENV_INT_OVERRIDES`.
