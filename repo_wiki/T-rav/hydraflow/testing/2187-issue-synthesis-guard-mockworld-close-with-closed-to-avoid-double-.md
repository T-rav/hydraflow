---
id: 2187
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.418555+00:00
status: superseded
corroborations: 1
supersedes: 2058
superseded_by: 2332
---

# Guard MockWorld.close() with _closed to avoid double-shutting OTel

`FakeHoneycomb.shutdown()` unconditionally nulls `trace._TRACER_PROVIDER`. Some existing tests already call `world.honeycomb.shutdown()` in their own teardown, so the autouse drain in `tests/conftest.py` can double-shutdown.

Example: `MockWorld.close()` must check an idempotent `_closed` flag before calling `FakeHoneycomb.shutdown()` and uninstalling the subprocess clock.

**Why:** Without the guard, the second shutdown nulls a provider another live world installed and raises on already-retired providers.
