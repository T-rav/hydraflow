---
id: 2335
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.062529+00:00
status: active
corroborations: 1
supersedes: 2190
---

# Derive test scrub sets from declared_env_keys(), never hand-list

Use `src/config.py::declared_env_keys()` to compute the conftest scrub set at runtime — union its return with the `HYDRAFLOW_*`/`HYDRA_*` prefix rule and `GIT_*` list. Adding a non-prefixed entry to any `_ENV_*_OVERRIDES` table propagates to test isolation with zero edits to `tests/conftest.py`.

**Why:** A hand-maintained list in conftest silently drifts from the config tables, leaking host env into `HydraFlowConfig` for the entire test session.
