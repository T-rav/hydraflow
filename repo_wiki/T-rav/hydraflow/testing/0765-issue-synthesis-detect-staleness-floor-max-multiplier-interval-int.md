---
id: 0765
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:12:20.307220+00:00
status: active
corroborations: 1
supersedes: 0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753
---

# detect_staleness floor: max(multiplier*interval, interval+max_cycle_s)

Floor `detect_staleness`'s threshold in `src/trust_fleet_anomaly_detectors.py` at `threshold_s = max(multiplier * interval_s, interval_s + max_cycle_s)` instead of a bare `multiplier * interval_s`, which false-positives on workers with short poll intervals but long work cycles.

Example: `staging_bisect` polls every 600s but has cycles up to 2700s; default `max_cycle_s=0` (keyword-only) keeps existing callers/tests unaffected, and `max_cycle_s` is included in the returned details dict for observability. See also: TrustFleetSanityLoop staleness tuning needs unit+regression+scenario layers.

**Why:** heartbeats only refresh on cycle completion (`src/base_background_loop.py`), so a healthy worker can legitimately lag one poll interval plus one full cycle — a flat multiplier misreads that as wedged.
