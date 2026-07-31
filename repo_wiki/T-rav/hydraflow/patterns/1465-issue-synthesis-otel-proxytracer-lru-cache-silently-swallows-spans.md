---
id: 1465
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T16:53:02.245348+00:00
status: active
corroborations: 1
supersedes: 1387
---

# OTel ProxyTracer lru_cache silently swallows spans against dead providers

`_get_tracer` in `src/telemetry/spans.py` is an `lru_cache` of OTel `ProxyTracer`s that memoise `_real_tracer` on first resolution. A tracer cached against a dead provider silently swallows spans. Always invalidate the cache after swapping providers via `reset_tracer_cache()`.

Example: `FakeHoneycomb.__init__` calls `reset_tracer_cache()` immediately after `trace.set_tracer_provider(self._provider)` — order is load-bearing; inverting it re-caches against the old provider.

**Why:** Without invalidation, production spans emitted after a provider swap are dispatched to a tracer bound to the old, shut-down provider and vanish silently.
