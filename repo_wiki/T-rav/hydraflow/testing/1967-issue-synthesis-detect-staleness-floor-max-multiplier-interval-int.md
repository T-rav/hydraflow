---
id: 1967
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:52.843175+00:00
status: active
corroborations: 1
supersedes: 1840
---

# detect_staleness floor: max(multiplier*interval, interval+max_cycle_s)

Floor detect_staleness's threshold in src/trust_fleet_anomaly_detectors.py at `threshold_s = max(multiplier * interval_s, interval_s + max_cycle_s)` instead of a bare `multiplier * interval_s`.

Example: staging_bisect polls every 600s but has cycles up to 2700s; default max_cycle_s=0 keeps existing callers unaffected.

**Why:** Heartbeats only refresh on cycle completion (src/base_background_loop.py), so a healthy worker can legitimately lag one poll interval plus one full cycle.
