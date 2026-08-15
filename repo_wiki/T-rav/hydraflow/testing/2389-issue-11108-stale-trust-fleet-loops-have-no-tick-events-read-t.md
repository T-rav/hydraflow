---
id: 2389
topic: testing
source_issue: 11108
source_phase: plan
created_at: 2026-08-14T09:10:42.283847+00:00
status: superseded
corroborations: 1
superseded_by: 2577
---

# Stale trust-fleet loops have no tick events; read trace files instead

For staleness diagnostics on per-worker loops, read age-unbounded trace files at `<data_root>/traces/_loops/<slug>/run-*.json`, never the tick's 24h event window.

- A 7-day-interval loop like `fake_coverage_auditor` has zero events in the 24h window.
- Trace files persist across all runs regardless of cadence.

**Why:** Using the event window for a long-cadence loop produces empty diagnostics, reproducing the #11094 blind-spot where autonomous retry had nothing to act on.
