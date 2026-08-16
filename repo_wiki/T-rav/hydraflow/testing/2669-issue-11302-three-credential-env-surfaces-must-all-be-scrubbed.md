---
id: 2669
topic: testing
source_issue: 11302
source_phase: plan
created_at: 2026-08-16T04:43:31.977946+00:00
status: active
corroborations: 1
---

# Three credential env surfaces must all be scrubbed in conftest

Every credential env var in this repo falls into one of three surfaces that `tests/conftest.py::setup_test_environment` must scrub together:

- `declared_env_keys()` — the `_ENV_*_OVERRIDES` tables
- `CREDENTIAL_ENV_KEYS` — covers `build_credentials`
- `PROVIDER_API_KEY_ENVS` — union of `api_key_envs` across `_OPENAI_COMPAT_BACKENDS` and `_HARNESS_BACKENDS` in `src/runner_utils.py`

Missing any surface leaks real keys from `.env` into test bodies.

**Why:** A scrub covering only one or two surfaces leaves a gap that appears only when a developer's `.env` carries live provider keys, making the suite non-hermetic.
