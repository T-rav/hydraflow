---
id: 0781
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:12:20.340278+00:00
status: active
corroborations: 1
supersedes: 0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753
---

# Fresh sandbox has no cadence marker — RC cut fires on tick 1

`StagingPromotionLoop`'s `_cadence_elapsed()` check (governed by `rc_cadence_hours`) is true by default when no prior cadence marker exists, so a scenario seeding a fresh sandbox doesn't need to fake or shrink the cadence to get an RC cut immediately.

Example: just run ≥2 ticks and assert via a full `/api/events` scan (not the latest page) to avoid timing flake.

**Why:** assuming cadence needs mocking leads to unnecessary scenario complexity; the real gotcha is asserting on the wrong event-page window.
