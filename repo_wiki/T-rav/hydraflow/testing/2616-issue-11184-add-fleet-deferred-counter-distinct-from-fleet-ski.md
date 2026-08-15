---
id: 2616
topic: testing
source_issue: 11184
source_phase: plan
created_at: 2026-08-14T23:44:16.701439+00:00
status: active
corroborations: 1
---

# Add fleet_deferred counter distinct from fleet_skipped and fleet_errors

Keep budget-driven deferrals observable via a `fleet_deferred` counter in `AdrDriftResolverLoop` tick results, separate from `fleet_skipped` and `fleet_errors`.

- A deferred batch increments `fleet_deferred` only — not `fleet_skipped`/`fleet_errors`.
- The tick result dict gains a new key; consumers reading it must tolerate additions (verify no strict-schema assertion in existing tests).

**Why:** Without a separate counter, deferred batches are invisible, making config-level mis-sizing (e.g., `max_triage_per_tick` below smallest batch size) impossible to diagnose from observability alone.
