---
id: 0723
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.163626+00:00
status: superseded
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
superseded_by: 0754
---

# detect_staleness floor: max(multiplier*interval, interval+max_cycle_s)

Floor `detect_staleness`'s threshold in `src/trust_fleet_anomaly_detectors.py` at `threshold_s = max(multiplier * interval_s, interval_s + max_cycle_s)` instead of a bare `multiplier * interval_s`, which false-positives on workers with short poll intervals but long work cycles.

Example: `staging_bisect` polls every 600s but has cycles up to 2700s; default `max_cycle_s=0` (keyword-only) keeps existing callers/tests unaffected, and `max_cycle_s` is included in the returned details dict for observability. See also: testing — TrustFleetSanityLoop staleness tuning needs unit + regression + scenario layers.

**Why:** heartbeats only refresh on cycle completion (`src/base_background_loop.py`), so a healthy worker can legitimately lag one poll interval plus one full cycle — a flat multiplier misreads that as wedged.
