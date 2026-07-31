---
id: 2081
topic: testing
source_issue: 10890
source_phase: plan
created_at: 2026-07-31T12:12:42.365177+00:00
status: active
corroborations: 1
---

# Reuse `_reset_otel_tracer_provider` for OTel test teardown

Reuse the autouse `_reset_otel_tracer_provider` fixture (tests/conftest.py:282) for OTel teardown; do not add bespoke reset helpers in per-test conftest files.

- OTel `TracerProvider` registers via a `Once`; without teardown it leaks across tests and flakes under `pytest -n auto`.
- Duplicating a reset helper conflicts with the shared fixture's lifecycle and reintroduces ordering-dependent state.

**Why:** Bespoke resets cause intermittent tracer-provider errors under parallel test execution and break the single-teardown invariant.
