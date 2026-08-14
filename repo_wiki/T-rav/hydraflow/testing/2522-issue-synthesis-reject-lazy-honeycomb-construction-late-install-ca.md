---
id: 2522
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:50.896292+00:00
status: active
corroborations: 1
supersedes: 2333
---

# Reject lazy honeycomb construction — late install captures zero spans

`FakeHoneycomb` must be constructed eagerly in `MockWorld.__init__`; do not defer it.

Example: a tempting alternative was to build the `FakeHoneycomb`/`TracerProvider` lazily on first `world.honeycomb` access. This was rejected.

**Why:** A world whose `honeycomb` property is first touched *after* `run_pipeline()` has already emitted spans would install the provider too late and silently capture nothing, making `tests/scenarios/test_telemetry_e2e.py` flake rather than fail loudly.
