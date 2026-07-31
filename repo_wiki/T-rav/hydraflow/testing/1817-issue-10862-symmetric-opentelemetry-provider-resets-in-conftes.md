---
id: 1817
topic: testing
source_issue: 10862
source_phase: plan
created_at: 2026-07-31T02:48:15.326702+00:00
status: active
corroborations: 1
---

# Symmetric OpenTelemetry provider resets in conftest

Reset OpenTelemetry tracer providers *before and after* each test in `tests/conftest.py`. Call the identity-agnostic `reset_tracer_cache()` alongside the provider reset.

**Why:** If a previous test abandons a `FakeHoneycomb` without `shutdown()`, the next test's provider installation is silently ignored. Symmetric resets ensure each test starts clean and abandons nothing.
