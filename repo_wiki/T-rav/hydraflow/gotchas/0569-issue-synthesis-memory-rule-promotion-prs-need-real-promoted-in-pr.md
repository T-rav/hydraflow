---
id: 0569
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:39:28.196283+00:00
status: active
corroborations: 1
supersedes: 0494,0495,0496,0497,0498,0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539
---

# Memory-rule promotion PRs need real promoted_in PR# and Closes # in body

When flipping a memory rule from "remembered" to "structurally enforced" (ADR-0089), the mirror file (e.g. `docs/wiki/memory-feedback/feedback-monitor-fix-merge-prs.md`) frontmatter must be updated to `status: promoted` with the actual PR number in `promoted_in` (filled after `gh pr create`, not a placeholder), and the PR body must contain `Closes #<issue>`.

**Why:** A placeholder `promoted_in` or missing `Closes #` lets `MemoryBacklogLoop` re-file the same rule as an open backlog item.
