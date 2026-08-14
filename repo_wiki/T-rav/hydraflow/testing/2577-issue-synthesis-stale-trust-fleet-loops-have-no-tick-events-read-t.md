---
id: 2577
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.730309+00:00
status: active
corroborations: 1
supersedes: 2389
---

# Stale trust-fleet loops have no tick events; read trace files

For staleness diagnostics on per-worker loops, read age-unbounded trace files at `<data_root>/traces/_loops/<slug>/run-*.json`, never the tick's 24h event window.

Example: a 7-day-interval loop like `fake_coverage_auditor` has zero events in the 24h window. Trace files persist across all runs regardless of cadence.

**Why:** Using the event window for a long-cadence loop produces empty diagnostics, reproducing the #11094 blind-spot where autonomous retry had nothing to act on.
