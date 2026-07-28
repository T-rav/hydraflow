---
id: 1182
topic: gotchas
source_issue: 10751
source_phase: plan
created_at: 2026-07-27T23:15:11.981959+00:00
status: active
corroborations: 1
---

# Split BackgroundWorkerStatus consumers: tallies vs state

Cycle-counting tallies (restarts, `ticks_total`/`ticks_errored`, loop fitness, cost rollups) must exclude seeded events; last-known-state views (sticky slice, `loopsHealthy {ok,total}`, severity) read them unchanged.

- `src/ui/src/operator/model/vitals.js` — skip seeded in restart tally
- `src/ui/src/operator/model/loops.js` — `countErrorCycles` skips seeded
- `src/dashboard_routes/_trust_routes.py`, `_cost_rollups.py` — drop seeded before tallying

**Why:** Seeded events are restored state, not observed cycles — counting them inflates metrics with phantom failures.
