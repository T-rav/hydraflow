---
id: 0482
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:41:04.372190+00:00
status: active
corroborations: 1
supersedes: 0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445,0446,0447,0448,0449,0450
---

# Memory dedup: higher-priority bank wins on collision

When two near-duplicate items collide, the higher-priority bank's item survives.

Example: Priority order: LEARNINGS (5) > TROUBLESHOOTING (4) > RETROSPECTIVES (3) > REVIEW_INSIGHTS (2) > HARNESS_INSIGHTS (1). Test collision behavior explicitly.

**Why:** Without priority enforcement, a lower-quality retrospective can silently overwrite a load-bearing learning entry.
