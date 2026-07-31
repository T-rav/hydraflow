---
id: 1950
topic: testing
source_issue: 10889
source_phase: plan
created_at: 2026-07-31T10:36:59.292261+00:00
status: active
corroborations: 1
---

# src.-prefixed imports in tests/conftest.py create duplicate module objects

Never import from `src.` prefix in `tests/conftest.py`. Production code imports `telemetry.spans` as a bare alias; importing `src.telemetry.spans` creates a separate module object where `a is b` → `False`. A fixture calling `_get_tracer.cache_clear()` on the conftest-side alias clears the wrong cache, leaving the production-side cache polluted across tests. Use the bare alias everywhere.

**Why:** Cache/fixture clears silently miss their target, making test-boundary resets ineffective and producing order-dependent failures under xdist.
