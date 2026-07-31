---
id: 1572
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T01:04:04.344838+00:00
status: active
corroborations: 1
supersedes: 1490
---

# Fresh sandbox has no cadence marker — RC cut fires on tick 1

StagingPromotionLoop's _cadence_elapsed() check (governed by rc_cadence_hours) is true by default when no prior cadence marker exists, so a scenario seeding a fresh sandbox doesn't need to fake or shrink the cadence to get an RC cut immediately.

Example: just run ≥2 ticks and assert via a full /api/events scan (not the latest page) to avoid timing flake.

**Why:** Assuming cadence needs mocking leads to unnecessary scenario complexity; the real gotcha is asserting on the wrong event-page window.
