---
id: 0822
topic: gotchas
source_issue: 10488
source_phase: plan
created_at: 2026-07-24T21:53:09.549066+00:00
status: active
corroborations: 1
---

# StreamView badges derive from stageGroups, not a new endpoint

Pipeline flow region counts/badges must be computed from the same `stageGroups` that `PipelineFlow` already builds (`StreamView.jsx:374`), never a new `/api/pipeline` call or parallel aggregation. Issues per region = `group.issues.length`; PRs per region = issues whose `pr` was already resolved by `toStreamIssue` (`StreamView.jsx:290`) against context `prs[]` — do not re-match against `prs[]` downstream.

**Why:** a second source of truth for board state can drift from what the cards actually render, producing counts that disagree with visible cards.
