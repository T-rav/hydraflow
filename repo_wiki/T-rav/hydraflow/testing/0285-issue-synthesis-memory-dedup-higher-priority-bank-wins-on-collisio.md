---
id: 0285
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:48:26.498145+00:00
status: superseded
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
superseded_by: 0295
---

# Memory dedup: higher-priority bank wins on collision

When two near-duplicate items collide, the higher-priority bank's item survives.

Priority order: LEARNINGS (5) > TROUBLESHOOTING (4) > RETROSPECTIVES (3) > REVIEW_INSIGHTS (2) > HARNESS_INSIGHTS (1). Test collision behavior explicitly, not just deduplication count.

**Why:** Without priority enforcement, a lower-quality retrospective can silently overwrite a load-bearing learning entry.
