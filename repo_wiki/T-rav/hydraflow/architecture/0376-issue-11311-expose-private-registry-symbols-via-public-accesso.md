---
id: 0376
topic: architecture
source_issue: 11311
source_phase: plan
created_at: 2026-08-16T07:14:25.767539+00:00
status: active
corroborations: 1
---

# Expose private registry symbols via public accessors

When tests or regression pins need a `_`-prefixed module symbol, add a public accessor instead of importing the private name with `# noqa: SLF001`.

- `src/credit_failover.py`: `zai_api_key_envs() -> tuple[str, ...]` returns `_ZAI_API_KEY_ENVS`.
- `src/runner_utils.py`: `provider_api_key_envs() -> frozenset[str]` derives from `_OPENAI_COMPAT_BACKENDS` and `_HARNESS_BACKENDS`.

**Why:** Cross-module `_` imports break encapsulation and make future registry renaming brittle across pins and conftest helpers.
