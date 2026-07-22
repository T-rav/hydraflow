---
id: 0564
topic: testing
source_issue: 10236
source_phase: plan
created_at: 2026-07-22T17:17:17.227674+00:00
status: active
corroborations: 1
---

# detect_staleness floor: max(multiplier*interval, interval+max_cycle_s)

In `src/trust_fleet_anomaly_detectors.py`, a bare `multiplier * interval_s` staleness threshold false-positives on workers with short poll intervals but long work cycles (e.g. staging_bisect: 600s poll, cycles up to 2700s). Floor the threshold instead: `threshold_s = max(multiplier * interval_s, interval_s + max_cycle_s)`. Default `max_cycle_s=0` (keyword-only) so existing callers/tests are unaffected. Include `max_cycle_s` in the returned details dict for observability.

**Why:** heartbeats only refresh on cycle completion (`src/base_background_loop.py`), so a healthy worker can legitimately lag one poll interval plus one full cycle — a flat multiplier misreads that as wedged.
