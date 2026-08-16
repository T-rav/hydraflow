---
id: 2681
topic: testing
source_issue: 11311
source_phase: plan
created_at: 2026-08-16T07:14:25.767528+00:00
status: active
corroborations: 1
---

# Keep CREDENTIAL_ENV_KEYS disjoint from provider API key envs

Do not fold provider API key envs (`ZAI_API_KEY`, `ZAI_CODING_PLAN_KEY`, etc.) into `CREDENTIAL_ENV_KEYS`; keep that set scoped to `build_credentials` and disjoint from `declared_env_keys()`.

- `tests/test_credentials_registry.py` asserts `CREDENTIAL_ENV_KEYS ∩ declared_env_keys() = ∅`.
- Provider keys belong to the backend-registry scrub surface, not the credentials model.

**Why:** Folding provider keys in breaks the credentials-registry disjointness invariant and misattributes them to `build_credentials`.
