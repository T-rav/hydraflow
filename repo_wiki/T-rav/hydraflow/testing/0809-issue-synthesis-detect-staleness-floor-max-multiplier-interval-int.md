---
id: 0809
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:43:21.179280+00:00
status: active
corroborations: 1
supersedes: 0754,0755,0756,0757,0758,0759,0760,0761,0762,0763,0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797
---

# detect_staleness floor: max(multiplier*interval, interval+max_cycle_s)

Floor `detect_staleness`'s threshold in `src/trust_fleet_anomaly_detectors.py` at `threshold_s = max(multiplier * interval_s, interval_s + max_cycle_s)` instead of a bare `multiplier * interval_s`, which false-positives on workers with short poll intervals but long work cycles.

Example: `staging_bisect` polls every 600s but has cycles up to 2700s; default `max_cycle_s=0` (keyword-only) keeps existing callers/tests unaffected, and `max_cycle_s` is included in the returned details dict for observability. See also: TrustFleetSanityLoop staleness tuning needs unit+regression+scenario layers.

**Why:** heartbeats only refresh on cycle completion (`src/base_background_loop.py`), so a healthy worker can legitimately lag one poll interval plus one full cycle — a flat multiplier misreads that as wedged.
