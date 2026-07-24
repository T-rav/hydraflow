---
id: 0518
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.788561+00:00
status: active
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
---

# Memory-rule promotion PRs need real promoted_in PR# and Closes # in body

When flipping a memory rule from "remembered" to "structurally enforced" (ADR-0089), the mirror file (e.g. `docs/wiki/memory-feedback/feedback-monitor-fix-merge-prs.md`) frontmatter must be updated to `status: promoted` with the actual PR number in `promoted_in` (filled after `gh pr create`, not a placeholder), and the PR body must contain `Closes #<issue>`.

**Why:** A placeholder `promoted_in` or missing `Closes #` lets `MemoryBacklogLoop` re-file the same rule as an open backlog item.
