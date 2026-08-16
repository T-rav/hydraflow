---
id: 0372
topic: architecture
source_issue: 11307
source_phase: plan
created_at: 2026-08-16T05:25:13.887897+00:00
status: active
corroborations: 1
---

# Advisory vitals loops use Pattern B and ADR-0049 gating

Implement advisory vitals loops as read-only Pattern B workers with ADR-0049 gating.
- `src/objective_change_rate_loop.py` must check the in-body enable gate and `dry_run` flag before harvesting.
- Cap filings with `FilingBudget` and persist the episode flag only after `create_issue` succeeds, mirroring `second_order_vitals._maybe_fire_alarm`.
**Why:** Prevents alert storms and ensures advisory loops do not mutate state prematurely.
