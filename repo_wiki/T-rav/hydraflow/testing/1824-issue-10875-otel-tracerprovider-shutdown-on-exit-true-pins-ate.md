---
id: 1824
topic: testing
source_issue: 10875
source_phase: plan
created_at: 2026-07-31T03:41:38.628235+00:00
status: superseded
corroborations: 1
superseded_by: 1928
---

# OTel TracerProvider(shutdown_on_exit=True) pins atexit for process lifetime

Any `FakeHoneycomb` constructed in tests builds an SDK `TracerProvider` with `shutdown_on_exit=True`, which calls `atexit.register(provider.shutdown)` — a strong reference that survives `trace._TRACER_PROVIDER` being reset by the `_reset_otel_tracer_provider` fixture. `FakeHoneycomb.shutdown()` unregisters it but nothing called it until issue #10875.

Rule: after creating a `MockWorld`, either close it explicitly (`world.close()` / `world.aclose()` / `with`) or rely on the autouse drain in `tests/conftest.py`.

**Why:** abandoned providers accumulate across the test session and inflate `atexit._ncallbacks()`; the regression pin in `tests/regressions/regression_issue_10875.py` guards this directly.
