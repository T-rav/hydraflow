---
id: 0858
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:22:24.422231+00:00
status: superseded
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
superseded_by: 0897
---

# detect_staleness floor: max(multiplier*interval, interval+max_cycle_s)

Floor `detect_staleness`'s threshold in `src/trust_fleet_anomaly_detectors.py` at `threshold_s = max(multiplier * interval_s, interval_s + max_cycle_s)` instead of a bare `multiplier * interval_s`, which false-positives on workers with short poll intervals but long work cycles.

Example: `staging_bisect` polls every 600s but has cycles up to 2700s; default `max_cycle_s=0` (keyword-only) keeps existing callers/tests unaffected, and `max_cycle_s` is included in the returned details dict for observability. See also: TrustFleetSanityLoop staleness tuning needs unit+regression+scenario layers.

**Why:** heartbeats only refresh on cycle completion (`src/base_background_loop.py`), so a healthy worker can legitimately lag one poll interval plus one full cycle — a flat multiplier misreads that as wedged.
