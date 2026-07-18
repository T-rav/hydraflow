---
id: 0031
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.411360+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Memory dedup: higher-priority bank wins on collision

When two near-duplicate items collide, the higher-priority bank's item survives. Priority order: LEARNINGS (5) > TROUBLESHOOTING (4) > RETROSPECTIVES (3) > REVIEW_INSIGHTS (2) > HARNESS_INSIGHTS (1).

Test collision behavior explicitly, not just deduplication count.

**Why:** Without priority enforcement, a lower-quality retrospective can silently overwrite a load-bearing learning entry.
