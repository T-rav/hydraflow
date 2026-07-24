---
id: 0620
topic: testing
source_issue: 10309
source_phase: plan
created_at: 2026-07-24T04:15:22.309958+00:00
status: superseded
corroborations: 1
superseded_by: 0632
---

# Fresh sandbox has no cadence marker, so StagingPromotionLoop's RC cut fires on tick 1

`StagingPromotionLoop`'s `_cadence_elapsed()` check (governed by `rc_cadence_hours`) is true by default when no prior cadence marker exists, so a scenario seeding a fresh sandbox doesn't need to fake or shrink the cadence to get an RC cut immediately — just run ≥2 ticks and assert via a full `/api/events` scan (not the latest page) to avoid timing flake.
**Why:** Assuming cadence needs mocking leads to unnecessary scenario complexity; the real gotcha is asserting on the wrong event-page window.
