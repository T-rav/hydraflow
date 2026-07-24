---
id: 0604
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:57:59.579627+00:00
status: superseded
corroborations: 1
supersedes: 0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0632
---

# detect_staleness floor: max(multiplier*interval, interval+max_cycle_s)

In `src/trust_fleet_anomaly_detectors.py`, a bare `multiplier * interval_s` staleness threshold false-positives on workers with short poll intervals but long work cycles (e.g. staging_bisect: 600s poll, cycles up to 2700s). Floor the threshold instead: `threshold_s = max(multiplier * interval_s, interval_s + max_cycle_s)`. Default `max_cycle_s=0` (keyword-only) so existing callers/tests are unaffected. Include `max_cycle_s` in the returned details dict for observability.

**Why:** heartbeats only refresh on cycle completion (`src/base_background_loop.py`), so a healthy worker can legitimately lag one poll interval plus one full cycle — a flat multiplier misreads that as wedged.
