---
id: 2206
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.467008+00:00
status: superseded
corroborations: 1
supersedes: 2077
superseded_by: 2350
---

# Force-reset OTel Once guard when installing FakeHoneycomb

When constructing `FakeHoneycomb` in `src/mockworld/fakes/fake_honeycomb.py`, manually reset the OpenTelemetry `Once` guard before calling `set_tracer_provider`. Set `trace._TRACER_PROVIDER_SET_ONCE._done = False` before installing the new provider.

Example: if a prior `MockWorld` provider was never shut down, the OTel `Once` guard blocks the new provider from being installed, causing spans to route to the wrong exporter.

**Why:** Without resetting the guard, stale provider state from a leaked MockWorld silently captures or drops spans from the current test.
