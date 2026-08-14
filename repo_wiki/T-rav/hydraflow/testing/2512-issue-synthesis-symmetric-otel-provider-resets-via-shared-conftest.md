---
id: 2512
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:50.755067+00:00
status: active
corroborations: 1
supersedes: 2323
---

# Symmetric OTel provider resets via shared conftest fixture

Reset OpenTelemetry tracer providers before and after each test in `tests/conftest.py` via the autouse `_reset_otel_tracer_provider` fixture (`tests/conftest.py:282`). Call `reset_tracer_cache()` alongside the provider reset. Never add bespoke reset helpers in per-test conftest files.

**Why:** Bespoke resets conflict with the shared fixture's lifecycle and reintroduce ordering-dependent state; symmetric resets ensure each test starts clean and abandons nothing.
