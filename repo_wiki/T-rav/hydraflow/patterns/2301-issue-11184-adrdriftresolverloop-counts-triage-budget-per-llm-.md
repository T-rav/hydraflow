---
id: 2301
topic: patterns
source_issue: 11184
source_phase: plan
created_at: 2026-08-14T23:44:16.701462+00:00
status: active
corroborations: 1
---

# AdrDriftResolverLoop counts triage budget per LLM classify call, not per batch

`AdrDriftResolverLoop._do_work` counts triage budget per LLM `classify` call, and an oversized batch is deferred whole rather than started partway.

- With `adr_drift_resolver_max_triage_per_tick=2` and a 3-member batch, the batch is deferred; a trailing 1-member batch is triaged in the same tick.

**Why:** Per-call accounting keeps a tick's LLM spend bounded by config and prevents partial batch processing that would leave half-triaged rollups in an inconsistent state.
