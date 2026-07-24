---
id: 0426
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:55:43.297893+00:00
status: active
corroborations: 1
supersedes: 0370,0371,0372,0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
---

# Memory-rule promotion PRs need real promoted_in PR# and Closes # in body

When flipping a memory rule from "remembered" to "structurally enforced" (ADR-0089), the mirror file (e.g. `docs/wiki/memory-feedback/feedback-monitor-fix-merge-prs.md`) frontmatter must be updated to `status: promoted` with the *actual* PR number in `promoted_in` (filled after `gh pr create`, not a placeholder), and the PR body must contain `Closes #<issue>`.

**Why:** a placeholder `promoted_in` or missing `Closes #` lets `MemoryBacklogLoop` re-file the same rule as an open backlog item.
