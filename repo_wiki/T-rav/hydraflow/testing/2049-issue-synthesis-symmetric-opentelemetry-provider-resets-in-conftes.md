---
id: 2049
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:53.997493+00:00
status: active
corroborations: 1
supersedes: 1922
---

# Symmetric OpenTelemetry provider resets in conftest

Reset OpenTelemetry tracer providers *before and after* each test in `tests/conftest.py`. Call the identity-agnostic `reset_tracer_cache()` alongside the provider reset.

**Why:** If a previous test abandons a `FakeHoneycomb` without `shutdown()`, the next test's provider installation is silently ignored. Symmetric resets ensure each test starts clean and abandons nothing.
