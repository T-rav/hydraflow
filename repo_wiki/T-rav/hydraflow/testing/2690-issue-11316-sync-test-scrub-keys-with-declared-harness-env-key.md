---
id: 2690
topic: testing
source_issue: 11316
source_phase: plan
created_at: 2026-08-16T07:49:06.673206+00:00
status: active
corroborations: 1
---

# Sync test scrub_keys with declared_harness_env_keys

Union `declared_harness_env_keys()` into `setup_test_environment`'s `scrub_keys` in `tests/conftest.py` to ensure test session hermeticity.

Example: Import `declared_harness_env_keys` from `runner_utils` inside the fixture to avoid module-scope circular imports, then add it to the existing `scrub_keys` set.

**Why:** Deriving the scrub set from the single source of truth prevents drift between runner env writes and test environment sanitization.
