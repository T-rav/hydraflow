---
id: 0874
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:22:24.458738+00:00
status: superseded
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
superseded_by: 0898
---

# Fresh sandbox has no cadence marker — RC cut fires on tick 1

`StagingPromotionLoop`'s `_cadence_elapsed()` check (governed by `rc_cadence_hours`) is true by default when no prior cadence marker exists, so a scenario seeding a fresh sandbox doesn't need to fake or shrink the cadence to get an RC cut immediately.

Example: just run ≥2 ticks and assert via a full `/api/events` scan (not the latest page) to avoid timing flake.

**Why:** assuming cadence needs mocking leads to unnecessary scenario complexity; the real gotcha is asserting on the wrong event-page window.
