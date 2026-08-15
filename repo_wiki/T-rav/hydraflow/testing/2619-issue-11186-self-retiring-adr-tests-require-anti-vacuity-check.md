---
id: 2619
topic: testing
source_issue: 11186
source_phase: plan
created_at: 2026-08-15T00:14:35.607925+00:00
status: active
corroborations: 1
---

# Self-retiring ADR tests require anti-vacuity checks

When regression tests self-retire via `pytest.skip` for absent/non-live ADRs, add a companion test that runs every pin case against the real `docs/adr` directory and asserts zero skips. See P3 in `tests/regressions/test_issue_11186.py`.

**Why:** Without an anti-vacuity check, an over-broad liveness gate passes the guard by skipping everything, silently dropping all coverage.
