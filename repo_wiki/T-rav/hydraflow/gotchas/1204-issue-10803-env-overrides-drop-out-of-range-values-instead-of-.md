---
id: 1204
topic: gotchas
source_issue: 10803
source_phase: plan
created_at: 2026-07-28T10:46:37.886210+00:00
status: active
corroborations: 1
---

# Env overrides drop out-of-range values instead of crashing

`HYDRAFLOW_*` environment variables that violate Field `ge`/`le` bounds are silently dropped by `_apply_env_overrides`, leaving the default value. Conversely, hand-edited config JSONs or constructor kwargs carrying invalid values (e.g., `worker_stall_tight_multiplier=1`) raise `ValidationError` at boot.

**Why:** Config bound changes will break hand-edited JSONs immediately but are safe for environment variable consumers.
