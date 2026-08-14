---
id: 2534
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.069976+00:00
status: active
corroborations: 1
supersedes: 2345
---

# Scrub CREDENTIAL_ENV_KEYS before applying test_env in conftest

In `tests/conftest.py`, `setup_test_environment` must flatten and pop every key from `CREDENTIAL_ENV_KEYS` **before** `patch.dict(os.environ, test_env)`, then restore originals in the existing `finally`.

Example: scrub-first blocks host-exported `GITHUB_TOKEN`/`SENTRY_AUTH_TOKEN` while preserving session fixtures. Scrub-after would delete `GH_TOKEN=test-token` from `test_env` and cascade across gh-dependent tests.

**Why:** Ordering is load-bearing — scrub-first isolates host leakage; scrub-after breaks the test session's own token contract.
