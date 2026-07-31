---
id: 2071
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:54.408773+00:00
status: superseded
corroborations: 1
supersedes: 1946
superseded_by: 2200
---

# Scrub CREDENTIAL_ENV_KEYS before applying test_env in conftest

In `tests/conftest.py`, `setup_test_environment` must flatten and pop every key from `CREDENTIAL_ENV_KEYS` **before** `patch.dict(os.environ, test_env)`, then restore originals in the existing `finally`.

Example: Scrub-first blocks host-exported `GITHUB_TOKEN`/`SENTRY_AUTH_TOKEN` while preserving session fixtures. Scrub-after would delete `GH_TOKEN=test-token` from `test_env` and cascade across gh-dependent tests.

**Why:** Ordering is load-bearing — scrub-first isolates host leakage; scrub-after breaks the test session's own token contract.
