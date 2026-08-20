---
id: 0270
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T17:52:50.703714+00:00
status: superseded
corroborations: 1
supersedes: 0252
superseded_by: 0288
---

# Use public symbols for cross-module env logic

Do not use `_`-prefixed imports for environment keys or helper functions shared across `src/subprocess_util.py` and `src/runner_utils.py`.

Example: Export `HARNESS_ROUTING_ENV_KEYS` and `declared_harness_env_keys()` as public symbols. Derive downstream sets from the constant rather than hand-listing them.

**Why:** Private cross-module imports obscure the dependency graph and make the env-build invariant harder to enforce.
