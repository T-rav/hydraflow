---
id: 2685
topic: testing
source_issue: 11312
source_phase: plan
created_at: 2026-08-16T07:21:09.104020+00:00
status: active
corroborations: 1
---

# Derive provider key env names from backend registries

Export `PROVIDER_API_KEY_ENVS` by scanning `api_key_envs` from every entry in `_OPENAI_COMPAT_BACKENDS` and `_HARNESS_BACKENDS` at import time. Never hand-list provider env names in a separate constant.

- `src/runner_utils.py` derives the set; `tests/conftest.py` unions it into `scrub_keys` beside `CREDENTIAL_ENV_KEYS`.
- Bare provider names (e.g. `ZAI_CODING_PLAN_KEY`, `OPENROUTER_API_KEY`) carry no `HYDRAFLOW_` prefix and appear in neither credential registry, so they need explicit inclusion.

**Why:** A hand-listed mirror silently drifts when backends are added or removed, causing non-hermetic test sessions.
