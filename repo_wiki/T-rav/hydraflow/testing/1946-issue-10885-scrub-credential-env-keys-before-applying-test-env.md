---
id: 1946
topic: testing
source_issue: 10885
source_phase: plan
created_at: 2026-07-31T07:40:02.824265+00:00
status: active
corroborations: 1
---

# Scrub CREDENTIAL_ENV_KEYS before applying test_env in conftest

In `tests/conftest.py`, `setup_test_environment` must flatten and pop every key from `CREDENTIAL_ENV_KEYS` **before** `patch.dict(os.environ, test_env)`, then restore originals in the existing `finally`.

- Scrub-after would delete `GH_TOKEN=test-token` from `test_env` and cascade across gh-dependent tests.
- Scrub-first blocks host-exported `GITHUB_TOKEN`/`SENTRY_AUTH_TOKEN` while preserving session fixtures.

**Why:** Ordering is load-bearing — scrub-first isolates host leakage; scrub-after breaks the test session's own token contract.
