---
id: 0363
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:25:25.504047+00:00
status: active
corroborations: 1
supersedes: 0295,0296,0297,0298,0299,0300,0301,0302,0303,0304,0305,0306,0307,0308,0309,0310,0311,0312,0313,0314,0315,0316,0317,0318,0319,0320,0321,0322,0323,0324,0325,0326,0327,0328,0329,0330,0331,0332,0333
---

# Memory dedup: higher-priority bank wins on collision

When two near-duplicate items collide, the higher-priority bank's item survives.

Example: Priority order: LEARNINGS (5) > TROUBLESHOOTING (4) > RETROSPECTIVES (3) > REVIEW_INSIGHTS (2) > HARNESS_INSIGHTS (1). Test collision behavior explicitly.

**Why:** Without priority enforcement, a lower-quality retrospective can silently overwrite a load-bearing learning entry.
