---
id: 2680
topic: testing
source_issue: 11311
source_phase: plan
created_at: 2026-08-16T07:14:25.767499+00:00
status: active
corroborations: 1
---

# Derive test env scrub from live backend registries, not a static list

Union `provider_api_key_envs()` from `src/runner_utils.py` into `scrub_keys` inside `setup_test_environment` (`tests/conftest.py`); provider registry keys like `ZAI_API_KEY` are neither `HYDRAFLOW_*`-prefixed, in `declared_env_keys()`, nor in `CREDENTIAL_ENV_KEYS`.

- `Makefile` uses `-include .env` + `export`, re-promoting `ZAI_CODING_PLAN_KEY` on every `make quality`.
- The scrub surface must be runtime-derived from `_OPENAI_COMPAT_BACKENDS` and `_HARNESS_BACKENDS` — no hand-maintained list.

**Why:** Leaked ambient credentials bypass "no key" preconditions in ADR conformance tests, producing false reroute assertions.
