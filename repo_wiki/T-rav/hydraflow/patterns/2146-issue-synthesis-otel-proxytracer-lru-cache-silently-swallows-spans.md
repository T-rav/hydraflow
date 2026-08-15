---
id: 2146
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T23:28:16.467897+00:00
status: superseded
corroborations: 1
supersedes: 2030
superseded_by: 2262
---

# OTel ProxyTracer lru_cache silently swallows spans against dead providers

Always invalidate the `_get_tracer` lru_cache after swapping providers via `reset_tracer_cache()` in `src/telemetry/spans.py`.

Example: `FakeHoneycomb.__init__` calls `reset_tracer_cache()` immediately after `trace.set_tracer_provider(self._provider)` — order is load-bearing; inverting it re-caches against the old provider.

**Why:** Without invalidation, production spans emitted after a provider swap are dispatched to a tracer bound to the old, shut-down provider and vanish silently.
