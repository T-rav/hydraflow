---
id: 0659
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:31:08.505103+00:00
status: superseded
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631
superseded_by: 0672
---

# Fresh sandbox has no cadence marker — RC cut fires on tick 1

`StagingPromotionLoop`'s `_cadence_elapsed()` check (governed by `rc_cadence_hours`) is true by default when no prior cadence marker exists, so a scenario seeding a fresh sandbox doesn't need to fake or shrink the cadence to get an RC cut immediately — just run ≥2 ticks and assert via a full `/api/events` scan (not the latest page) to avoid timing flake.

**Why:** Assuming cadence needs mocking leads to unnecessary scenario complexity; the real gotcha is asserting on the wrong event-page window.
