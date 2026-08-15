---
id: 1378
topic: gotchas
source_issue: 11217
source_phase: plan
created_at: 2026-08-15T06:04:15.266802+00:00
status: active
corroborations: 1
---

# Orphan branch detection: tip-vs-merge-head sha, not ahead-by count

For caretaker loops that flag orphaned branches after merge, use the branch tip sha vs the PR's merge-time head sha as the discriminator — never `ahead_by > 0` alone.

Every surviving squash-merged branch is ahead of its base, so `ahead_by > 0` files a false issue per merged PR. The `OrphanBranchLoop` (ADR-0029/0049) instead checks: tip differs from merge-time head sha, carries commits absent from base, and has no open PR.

**Why:** Without the tip-sha comparison, the loop becomes a noise generator — one spurious issue per merged PR.
