---
id: 1934
topic: testing
source_issue: 10876
source_phase: plan
created_at: 2026-07-31T05:37:16.290781+00:00
status: active
corroborations: 1
---

# Derive test scrub sets from declared_env_keys(), never hand-list them

Use `src/config.py::declared_env_keys()` to compute the conftest scrub set at runtime — union its return with the `HYDRAFLOW_*`/`HYDRA_*` prefix rule and `GIT_*` list. Adding a non-prefixed entry to any `_ENV_*_OVERRIDES` table (e.g. a new `SENTRY_*` key) propagates to test isolation with zero edits to `tests/conftest.py`. **Why:** a hand-maintained list in conftest silently drifts from the config tables, leaking host env into `HydraFlowConfig` for the entire test session.
