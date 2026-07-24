---
id: 0578
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:13:41.430090+00:00
status: superseded
corroborations: 1
supersedes: 0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566
superseded_by: 0593
---

# detect_staleness floor: max(multiplier*interval, interval+max_cycle_s)

In `src/trust_fleet_anomaly_detectors.py`, a bare `multiplier * interval_s` staleness threshold false-positives on workers with short poll intervals but long work cycles (e.g. staging_bisect: 600s poll, cycles up to 2700s). Floor the threshold instead: `threshold_s = max(multiplier * interval_s, interval_s + max_cycle_s)`. Default `max_cycle_s=0` (keyword-only) so existing callers/tests are unaffected. Include `max_cycle_s` in the returned details dict for observability.

**Why:** heartbeats only refresh on cycle completion (`src/base_background_loop.py`), so a healthy worker can legitimately lag one poll interval plus one full cycle — a flat multiplier misreads that as wedged.
