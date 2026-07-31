---
id: 0291
topic: architecture
source_issue: 10903
source_phase: plan
created_at: 2026-07-31T11:47:02.704703+00:00
status: active
corroborations: 1
---

# Expose public `clear_tracer_cache()` for cross-module invalidation

Expose tracer cache invalidation as a public method. Add `clear_tracer_cache()` to `src/telemetry/spans.py` wrapping `_get_tracer.cache_clear()`. `FakeHoneycomb.__init__` and `tests/conftest.py` should call `clear_tracer_cache()` rather than importing the private `_get_tracer`. **Why:** Importing private `_get_tracer` across module boundaries violates underscore rules and risks divergence if the caching implementation changes.
