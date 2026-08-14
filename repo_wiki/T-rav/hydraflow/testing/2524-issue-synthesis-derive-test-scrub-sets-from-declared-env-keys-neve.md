---
id: 2524
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:50.932164+00:00
status: active
corroborations: 1
supersedes: 2335
---

# Derive test scrub sets from declared_env_keys(), never hand-list

Use `src/config.py::declared_env_keys()` to compute the conftest scrub set at runtime — union its return with the `HYDRAFLOW_*`/`HYDRA_*` prefix rule and `GIT_*` list. Adding a non-prefixed entry to any `_ENV_*_OVERRIDES` table propagates to test isolation with zero edits to `tests/conftest.py`.

**Why:** A hand-maintained list in conftest silently drifts from the config tables, leaking host env into `HydraFlowConfig` for the entire test session.
