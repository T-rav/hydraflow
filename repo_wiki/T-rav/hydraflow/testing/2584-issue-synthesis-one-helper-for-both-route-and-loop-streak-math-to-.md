---
id: 2584
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.831706+00:00
status: active
corroborations: 1
supersedes: 2398
---

# One helper for both route and loop streak math to prevent drift

When the same metric is computed in both `trust_fleet_sanity_loop.py` and `_trust_routes.py`, route both through a single shared helper in `trust_fleet_anomaly_detectors.py`.

Example: `summarize_status_timeline()` is called by both `_collect_window_metrics` (loop side) and `_tally_events` (route side); a test asserts they agree on the same event list.

**Why:** Divergent definitions silently produce different fleet-row values versus filed anomalies, eroding trust in the meta-observability layer.
