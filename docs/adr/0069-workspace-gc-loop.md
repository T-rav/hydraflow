# ADR-0069 — WorkspaceGCLoop: Autonomous Worktree Garbage Collection

**Status:** Proposed
**Date:** 2026-05-19
**Enforced by:** tests/test_workspace_gc_loop.py

## Context

The implementation phase creates a git worktree per issue via `WorkspacePort.create`. When a PR is merged, the post-work cleanup normally destroys the worktree. Three leak classes exist where cleanup does not run:

1. A PR is merged manually via the GitHub UI (not through the orchestrator's merge path).
2. A human resolves a HITL issue and closes the PR, bypassing the orchestrator.
3. The orchestrator crashes or is restarted while a cleanup step is in flight.

Over time these leaks accumulate worktree directories on disk, orphaned branches on the remote, and stale `StateTracker` entries. The disk pressure and remote branch clutter are visible noise; the stale state entries can cause the pipeline to treat an issue as in-flight when it is not.

## Decision

Introduce `WorkspaceGCLoop`, a `BaseBackgroundLoop` that runs a three-phase GC pass on every tick:

1. **Phase 1 — tracked workspaces:** for each entry in `StateTracker.get_active_workspaces()`, check whether the PR is merged/closed; if safe, remove the state entry and call `WorkspacePort.destroy()`.
2. **Phase 2 — orphaned disk directories:** scan the worktree root for directories that have no `StateTracker` entry and no open PR.
3. **Phase 3 — orphaned remote branches:** list remote `issue/*` branches with no open PR and no `StateTracker` entry.

Cap at `_MAX_GC_PER_CYCLE = 20` collections per tick to avoid long-running passes. State removal precedes `destroy()` so a crash between the two steps leaves the entry gone rather than leaking permanently (`destroy()` is idempotent).

Kill-switch: `enabled_cb("workspace_gc")` AND `config.workspace_gc_loop_enabled`.

## Consequences

- Worktree leaks become self-healing; operators do not need to run manual `git worktree prune` commands.
- The pipeline's active-workspace view in `StateTracker` reflects reality within one GC interval.
- The 20-per-cycle cap means large backlogs drain gradually; acceptable because GC is low-priority background work.

## Alternatives considered

- **GC at merge-path only.** Already the first line of defense, but does not cover manual merges, HITL closures, or crash-mid-cleanup.
- **Cron script outside the orchestrator.** Possible but adds an out-of-process dependency; the orchestrator already has the state context needed to decide what's safe to GC.

## Related

- `src/workspace_gc_loop.py:WorkspaceGCLoop`
- `src/ports.py:WorkspacePort`, `src/ports.py:PRPort`
- [ADR-0003](0003-git-worktrees-for-isolation.md) — Git Worktrees for Issue Isolation
- [ADR-0029](0029-caretaker-loop-pattern.md) — Caretaker Background Loop Pattern
