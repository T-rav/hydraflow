---
id: 0478
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:15:19.417544+00:00
status: active
corroborations: 1
supersedes: 0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462
---

# Config field naming mirrors sibling fields for discoverability

New `adr_drift_*` config fields in `src/config.py` should mirror the naming shape of existing sibling fields rather than inventing new conventions.

Example: `adr_drift_shared_infra_fanout_threshold` was named to mirror `adr_drift_fleet_batch_threshold`, keeping the `adr_drift_<concern>_threshold` pattern and its matching `_ENV_INT_OVERRIDES` env var (`HYDRAFLOW_ADR_DRIFT_SHARED_INFRA_FANOUT_THRESHOLD`) consistent with existing overrides.

**Why:** consistent naming lets future readers grep `adr_drift_` in `src/config.py` and immediately infer the env override name without checking `_ENV_INT_OVERRIDES`.
