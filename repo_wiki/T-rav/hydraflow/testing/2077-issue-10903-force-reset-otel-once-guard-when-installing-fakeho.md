---
id: 2077
topic: testing
source_issue: 10903
source_phase: plan
created_at: 2026-07-31T11:47:02.704623+00:00
status: superseded
corroborations: 1
superseded_by: 2206
---

# Force-reset OTel `Once` guard when installing FakeHoneycomb

When constructing `FakeHoneycomb` in `src/mockworld/fakes/fake_honeycomb.py`, manually reset the OpenTelemetry `Once` guard before calling `set_tracer_provider`. Set `trace._TRACER_PROVIDER_SET_ONCE._done = False` before installing the new provider. **Why:** If a prior `MockWorld` provider was never shut down, the OTel `Once` guard blocks the new provider from being installed, causing spans to route to the wrong exporter.
