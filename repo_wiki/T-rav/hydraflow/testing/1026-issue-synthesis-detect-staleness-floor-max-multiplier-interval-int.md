---
id: 1026
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.450557+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# detect_staleness floor: max(multiplier*interval, interval+max_cycle_s)

Floor detect_staleness's threshold in src/trust_fleet_anomaly_detectors.py at threshold_s = max(multiplier * interval_s, interval_s + max_cycle_s) instead of a bare multiplier * interval_s, which false-positives on workers with short poll intervals but long work cycles.

Example: staging_bisect polls every 600s but has cycles up to 2700s; default max_cycle_s=0 (keyword-only) keeps existing callers/tests unaffected, and max_cycle_s is included in the returned details dict for observability.

**Why:** heartbeats only refresh on cycle completion (src/base_background_loop.py), so a healthy worker can legitimately lag one poll interval plus one full cycle — a flat multiplier misreads that as wedged.
