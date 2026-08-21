---
source: feedback_beads_workflow.md
name: Keep factory task state in worktree JSONL
description: HydraFlow owns phase-task lifecycle in each implementation worktree;
  agents never invoke a database-backed task CLI
status: issue-open
issue: 26
promoted_in: null
wontfix_reason: null
created: '2026-03-28'
---

HydraFlow stores phase-task state only in the implementation worktree's
`.beads/issues.jsonl`. `BeadsManager` creates, validates, claims, and closes
those records. Agents must not invoke a task-tracking CLI, connect to a shared
database, or edit the JSONL file themselves.

**Why:** Per-worktree JSONL keeps concurrent factory runs isolated and makes
the committed task lifecycle travel with the implementation branch.

**How to apply:** Treat phase IDs in prompts as informational. Record broader
follow-up work through the active issue/PR workflow; leave task-store mutations
to the factory.
