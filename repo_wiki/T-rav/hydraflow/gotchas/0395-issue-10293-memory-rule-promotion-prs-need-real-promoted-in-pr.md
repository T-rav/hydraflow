---
id: 0395
topic: gotchas
source_issue: 10293
source_phase: plan
created_at: 2026-07-22T18:20:50.899467+00:00
status: active
corroborations: 1
---

# Memory-rule promotion PRs need real promoted_in PR# and Closes # in body

When flipping a memory rule from "remembered" to "structurally enforced" (ADR-0089), the mirror file (e.g. `docs/wiki/memory-feedback/feedback-monitor-fix-merge-prs.md`) frontmatter must be updated to `status: promoted` with the *actual* PR number in `promoted_in` (filled after `gh pr create`, not a placeholder), and the PR body must contain `Closes #<issue>`.
**Why:** a placeholder `promoted_in` or missing `Closes #` lets `MemoryBacklogLoop` re-file the same rule as an open backlog item.
