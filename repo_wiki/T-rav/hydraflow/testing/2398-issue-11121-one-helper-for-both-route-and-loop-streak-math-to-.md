---
id: 2398
topic: testing
source_issue: 11121
source_phase: plan
created_at: 2026-08-14T10:59:17.953126+00:00
status: active
corroborations: 1
---

# One helper for both route and loop streak math to prevent drift

When the same metric is computed in both `trust_fleet_sanity_loop.py` and `_trust_routes.py`, route both through a single shared helper in `trust_fleet_anomaly_detectors.py`.

Example: `summarize_status_timeline()` is called by both `_collect_window_metrics` (loop side) and `_tally_events` (route side); a test asserts they agree on the same event list.

**Why:** Divergent definitions silently produce different fleet-row values versus filed anomalies, eroding trust in the meta-observability layer.
