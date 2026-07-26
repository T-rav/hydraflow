---
id: 0909
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:46:40.762061+00:00
status: superseded
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
superseded_by: 0954
---

# detect_staleness floor: max(multiplier*interval, interval+max_cycle_s)

Floor `detect_staleness`'s threshold in `src/trust_fleet_anomaly_detectors.py` at `threshold_s = max(multiplier * interval_s, interval_s + max_cycle_s)` instead of a bare `multiplier * interval_s`, which false-positives on workers with short poll intervals but long work cycles.

Example: `staging_bisect` polls every 600s but has cycles up to 2700s; default `max_cycle_s=0` (keyword-only) keeps existing callers/tests unaffected, and `max_cycle_s` is included in the returned details dict for observability. See also: TrustFleetSanityLoop staleness tuning needs unit+regression+scenario layers.

**Why:** heartbeats only refresh on cycle completion (`src/base_background_loop.py`), so a healthy worker can legitimately lag one poll interval plus one full cycle — a flat multiplier misreads that as wedged.
