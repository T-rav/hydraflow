---
id: 2178
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.395682+00:00
status: active
corroborations: 1
supersedes: 2049,2081
---

# Symmetric OTel provider resets via shared conftest fixture

Reset OpenTelemetry tracer providers before and after each test in tests/conftest.py via the autouse `_reset_otel_tracer_provider` fixture (tests/conftest.py:282). Call `reset_tracer_cache()` alongside the provider reset. Never add bespoke reset helpers in per-test conftest files.

Example: A prior test abandoning a FakeHoneycomb without shutdown() causes the next test's provider installation to be silently ignored.

**Why:** Bespoke resets conflict with the shared fixture's lifecycle and reintroduce ordering-dependent state; symmetric resets ensure each test starts clean and abandons nothing.
