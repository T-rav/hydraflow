---
id: 0696
topic: gotchas
source_issue: 10449
source_phase: plan
created_at: 2026-07-24T12:33:05.988839+00:00
status: superseded
corroborations: 1
superseded_by: 0704
---

# Push landed branches immediately — worktree GC can orphan a verified commit

A fully verified commit (`cb1d5fd5`, the #10403 JsonlLedger split) was lost to a worktree-GC incident and stranded on an orphaned local branch (`agent/auto-agent-10403`) for issue #10449 to re-land. The fix was never defective — it just never got pushed before the worktree was reclaimed. **Why:** local-only commits in a worktree are one GC cycle from disappearing; push the branch right after committing instead of leaving verified work unpushed, per [`docs/wiki/gotchas.md`](docs/wiki/gotchas.md) worktree rules.
