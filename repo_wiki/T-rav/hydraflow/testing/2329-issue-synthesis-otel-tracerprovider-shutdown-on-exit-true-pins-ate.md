---
id: 2329
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.046314+00:00
status: active
corroborations: 1
supersedes: 2184
---

# OTel TracerProvider(shutdown_on_exit=True) pins atexit lifetime

Any `FakeHoneycomb` constructed in tests builds an SDK `TracerProvider` with `shutdown_on_exit=True`, which calls `atexit.register(provider.shutdown)` — a strong reference surviving `trace._TRACER_PROVIDER` resets. After creating a `MockWorld`, either close it explicitly (`world.close()` / `with`) or rely on the autouse drain in `tests/conftest.py`.

**Why:** Abandoned providers accumulate across the test session and inflate `atexit._ncallbacks()`; the regression pin in `tests/regressions/regression_issue_10875.py` guards this directly.
