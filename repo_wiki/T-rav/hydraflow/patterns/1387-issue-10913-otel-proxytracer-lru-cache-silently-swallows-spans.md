---
id: 1387
topic: patterns
source_issue: 10913
source_phase: plan
created_at: 2026-07-31T13:38:55.527420+00:00
status: superseded
corroborations: 1
superseded_by: 1465
---

# OTel ProxyTracer lru_cache silently swallows spans against dead providers

Rule: `_get_tracer` in `src/telemetry/spans.py` is an `lru_cache` of OTel `ProxyTracer`s that memoise `_real_tracer` on first resolution. A tracer cached against a dead provider silently swallows spans. Always invalidate the cache after swapping providers via `reset_tracer_cache()`.

Example: `FakeHoneycomb.__init__` calls `reset_tracer_cache()` immediately after `trace.set_tracer_provider(self._provider)` — order is load-bearing; inverting it re-caches against the old provider.

**Why:** Without invalidation, production spans emitted after a provider swap are dispatched to a tracer bound to the old, shut-down provider and vanish silently.
