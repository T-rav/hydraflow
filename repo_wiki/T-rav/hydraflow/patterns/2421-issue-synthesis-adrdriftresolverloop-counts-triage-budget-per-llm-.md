---
id: 2421
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T05:19:55.919903+00:00
status: active
corroborations: 1
supersedes: 2301
---

# AdrDriftResolverLoop counts triage budget per LLM classify call, not per batch

`AdrDriftResolverLoop._do_work` counts triage budget per LLM `classify` call, and an oversized batch is deferred whole rather than started partway.

Example: With `adr_drift_resolver_max_triage_per_tick=2` and a 3-member batch, the batch is deferred; a trailing 1-member batch is triaged in the same tick.

**Why:** Per-call accounting keeps a tick's LLM spend bounded by config and prevents partial batch processing that would leave half-triaged rollups in an inconsistent state.
