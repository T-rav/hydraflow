---
id: 1828
topic: testing
source_issue: 10875
source_phase: plan
created_at: 2026-07-31T03:41:38.628308+00:00
status: active
corroborations: 1
---

# Reject lazy honeycomb construction — late install captures zero spans

A tempting alternative to the `MockWorld.close()` retrofit was to build the `FakeHoneycomb`/`TracerProvider` lazily on first `world.honeycomb` access. This was rejected.

Rule: `FakeHoneycomb` must be constructed eagerly in `MockWorld.__init__`; do not defer it.

**Why:** a world whose `honeycomb` property is first touched *after* `run_pipeline()` has already emitted spans would install the provider too late and silently capture nothing, making `tests/scenarios/test_telemetry_e2e.py` flake rather than fail loudly.
