---
id: 2188
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.421106+00:00
status: superseded
corroborations: 1
supersedes: 2059
superseded_by: 2333
---

# Reject lazy honeycomb construction — late install captures zero spans

A tempting alternative to the `MockWorld.close()` retrofit was to build the `FakeHoneycomb`/`TracerProvider` lazily on first `world.honeycomb` access. This was rejected.

Example: `FakeHoneycomb` must be constructed eagerly in `MockWorld.__init__`; do not defer it.

**Why:** A world whose `honeycomb` property is first touched *after* `run_pipeline()` has already emitted spans would install the provider too late and silently capture nothing, making `tests/scenarios/test_telemetry_e2e.py` flake rather than fail loudly.
