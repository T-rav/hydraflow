---
id: 0728
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:18:53.836034+00:00
status: superseded
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
superseded_by: 0764
---

# Memory-rule promotion PRs need real promoted_in PR# and Closes # in body

When flipping a memory rule from "remembered" to "structurally enforced" (ADR-0089), the mirror file (e.g. `docs/wiki/memory-feedback/feedback-monitor-fix-merge-prs.md`) frontmatter must be updated to `status: promoted` with the actual PR number in `promoted_in` (filled after `gh pr create`, not a placeholder), and the PR body must contain `Closes #<issue>`.

**Why:** A placeholder `promoted_in` or missing `Closes #` lets `MemoryBacklogLoop` re-file the same rule as an open backlog item.
