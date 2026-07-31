---
id: 1827
topic: testing
source_issue: 10875
source_phase: plan
created_at: 2026-07-31T03:41:38.628297+00:00
status: superseded
corroborations: 1
superseded_by: 1931
---

# Guard MockWorld.close() with _closed to avoid double-shutting the OTel provider

`FakeHoneycomb.shutdown()` unconditionally nulls `trace._TRACER_PROVIDER`. Some existing tests already call `world.honeycomb.shutdown()` in their own teardown, so the autouse drain in `tests/conftest.py` can double-shutdown.

Rule: `MockWorld.close()` must check an idempotent `_closed` flag before calling `FakeHoneycomb.shutdown()` and uninstalling the subprocess clock.

**Why:** without the guard, the second shutdown nulls a provider another live world installed (harmless only because `_reset_otel_tracer_provider` resets per test) and raises on already-retired providers.
