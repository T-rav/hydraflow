---
id: 0598
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.342810+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# Config field naming mirrors sibling fields for discoverability

New `adr_drift_*` config fields in `src/config.py` should mirror the naming shape of existing sibling fields rather than inventing new conventions.

Example: `adr_drift_shared_infra_fanout_threshold` mirrors `adr_drift_fleet_batch_threshold`, keeping the `adr_drift_<concern>_threshold` pattern and its `_ENV_INT_OVERRIDES` env var consistent.

**Why:** consistent naming lets readers grep `adr_drift_` in `src/config.py` and infer the env override name without checking `_ENV_INT_OVERRIDES`.
