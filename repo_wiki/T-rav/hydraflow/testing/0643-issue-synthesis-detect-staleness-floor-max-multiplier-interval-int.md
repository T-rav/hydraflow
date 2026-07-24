---
id: 0643
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:31:08.490382+00:00
status: superseded
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631
superseded_by: 0672
---

# detect_staleness floor: max(multiplier*interval, interval+max_cycle_s)

In `src/trust_fleet_anomaly_detectors.py`, a bare `multiplier * interval_s` staleness threshold false-positives on workers with short poll intervals but long work cycles (e.g. staging_bisect: 600s poll, cycles up to 2700s). Floor the threshold instead: `threshold_s = max(multiplier * interval_s, interval_s + max_cycle_s)`. Default `max_cycle_s=0` (keyword-only) so existing callers/tests are unaffected. Include `max_cycle_s` in the returned details dict for observability. See also: testing — TrustFleetSanityLoop staleness tuning needs unit + regression + scenario layers.

**Why:** heartbeats only refresh on cycle completion (`src/base_background_loop.py`), so a healthy worker can legitimately lag one poll interval plus one full cycle — a flat multiplier misreads that as wedged.
