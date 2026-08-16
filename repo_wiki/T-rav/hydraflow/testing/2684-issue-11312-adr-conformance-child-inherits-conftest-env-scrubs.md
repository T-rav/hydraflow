---
id: 2684
topic: testing
source_issue: 11312
source_phase: plan
created_at: 2026-08-16T07:21:09.103986+00:00
status: active
corroborations: 1
---

# ADR conformance child inherits conftest env scrubs

Conformance subprocesses launched by `src/adr_conformance_runner.py` spawn pytest without an explicit `env=`, so the child loads `tests/conftest.py`. Any `scrub_keys` logic in conftest automatically reaches ADR conformance runs.

- Fixing env-isolation in `setup_test_environment`'s `scrub_keys` set also fixes `AdrConformanceLoop` failures.
- No need to duplicate scrub logic in the runner itself.

**Why:** Without knowing this inheritance, a fixer might patch the runner's env or the ADR text instead of the single conftest scrub, multiplying blast radius.
