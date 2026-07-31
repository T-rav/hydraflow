---
id: 1939
topic: testing
source_issue: 10874
source_phase: plan
created_at: 2026-07-31T06:49:10.357924+00:00
status: active
corroborations: 1
---

# Dual import identity causes silent conftest fixture no-ops

When a `tests/conftest.py` fixture imports a module under a different alias than production, the fixture mutates a different module object — cache clears and tracer resets are invisible to production code.

- `tests/conftest.py:292` `_reset_otel_tracer_provider` imported `telemetry.spans` bare (the #10862 no-op)
- `src/server.py:509` reads the cache from the canonical name
- The fixture ran without error but never cleared what production reads

**Why:** Python caches module objects per import path; mutations to one don't propagate to the other.
