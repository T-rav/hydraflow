---
id: 2692
topic: testing
source_issue: 11317
source_phase: plan
created_at: 2026-08-16T07:49:38.021607+00:00
status: active
corroborations: 1
---

# Scrub backend envs via `backend_api_key_envs`

Expand `scrub_keys` in `tests/conftest.py::setup_test_environment` to union with `backend_api_key_envs()`, alongside `CREDENTIAL_ENV_KEYS`.
Example: `scrub_keys = scrub_keys.union(backend_api_key_envs())`
**Why:** Ambient developer shell exports of backend keys (like `ZAI_CODING_PLAN_KEY`) leak into pytest and cause non-hermetic failures if not scrubbed session-wide.
