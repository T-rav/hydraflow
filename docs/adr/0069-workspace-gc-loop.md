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

Introduce `WorkspaceGCLoop`, a `BaseBackgroundLoop` that runs a five-phase GC pass on every tick:

1. **Phase 1 — tracked workspaces:** for each entry in `StateTracker.get_active_workspaces()`, require issue-policy safety plus the shared clean-and-landed predicate before removing state and calling `WorkspacePort.destroy()`.
2. **Phase 2 — orphaned disk directories:** scan the worktree root for directories that have no `StateTracker` entry, then apply the same issue-policy and landed checks before destruction.
3. **Phase 3 — orphaned remote branches:** list remote `issue/*` branches with no open PR and no `StateTracker` entry.
4. **Phase 4 — stale branch state:** prune branch-state entries only after their issue is safe and no worktree remains.
5. **Phase 5 — all-root worktrees:** enumerate authoritative `git worktree list --porcelain` entries under configured roots and apply the same landed predicate before direct worktree removal.

Issue state is necessary but never sufficient for worktree destruction. A
closed-as-not-planned issue can still own unpushed commits (#11503), and the
standard-path phases must not bypass the guard used by the all-root phase
(#11507).

The landed predicate is exact-HEAD-aware (#11502):

1. `origin/<base>..HEAD` at zero proves the HEAD is already ancestral.
2. An empty two-rev tree diff (`origin/<base>` versus `HEAD`) recognizes a
   fresh squash merge even though the original commit SHAs never landed.
3. Once the base advances and that tree diff naturally diverges, GitHub PR
   history is authoritative only when exactly one merged PR matches the
   configured integration base, branch name, and worktree's current `HEAD`
   SHA. A PR into another base—or a merely merged PR on a reused branch
   name—is not evidence that this HEAD landed on `origin/<base>`.

Malformed git output, unknown refs, absent registered paths, dirty worktrees,
branch/issue/path identity mismatches, GitHub read failures, truncated result
pages, and ambiguous exact matches all fail closed. An attributed candidate
must contain a `.git` marker and report its own canonical candidate path from
`git rev-parse --show-toplevel` before status is read; this prevents a nested
non-git directory or misdirected gitfile from borrowing another checkout's
proof. An empty, existing, unattributed non-git directory is the only non-git
candidate considered provably empty. Git comparisons are pinned to the
initially captured OID and the clean HEAD identity is re-read before
destruction, preventing a concurrent branch move from mixing proofs.

Cap at `_MAX_GC_PER_CYCLE = 20` collections per tick to avoid long-running passes. State removal precedes `destroy()` so a crash between the two steps leaves the entry gone rather than leaking permanently (`destroy()` is idempotent).

Kill-switch: `enabled_cb("workspace_gc")` AND `config.workspace_gc_loop_enabled`.

## Consequences

- Worktree leaks become self-healing; operators do not need to run manual `git worktree prune` commands.
- The pipeline's active-workspace view in `StateTracker` reflects reality within one GC interval.
- The 20-per-cycle cap means large backlogs drain gradually; acceptable because GC is low-priority background work.
- **Retry-window safety contract:** a worktree is never collected while an in-flight attempt may still be committing into it. `_is_safe_to_gc` (and the orphan-branch phase) consult `_in_retry_window`, which skips whenever *either* the implementation counter (`get_issue_attempts`) *or* the `auto_agent` convergence-ledger counter (`get_auto_agent_attempts`) is in-window (`0 < attempts < max`). Both counters are bumped before a run and cleared on success/close, so between those moments the issue is absent from every active set even though a live session owns the worktree. Consulting only the implementation counter let GC sweep an actively-running auto-agent worktree and lose its unpushed commits (#10459, the #10403 race). The residual last-attempt gap (`attempts == max` on the final run) is the same theoretical window the implementation guard has always had; fully closing it needs a live session lock/heartbeat, tracked separately.
- **Destroy-target identity contract:** phase 1 compares the state-recorded path
  with the config-derived path that `WorkspacePort.destroy(issue)` will
  actually remove. It never inspects one directory and deletes another.
- **Lossless ownership contract:** once at cycle start, GC validates the raw
  `active_workspaces` keys and canonicalizes their paths into a reverse
  path-to-owner map reused by phases 1, 2, and 5. Every owned path is skipped
  even when its directory name or current branch attributes to another issue.
  Non-integer/non-canonical/duplicate-equivalent keys and empty, relative,
  NUL-bearing, non-string, or unresolvable paths make ownership unknowable and
  disable the entire destructive cycle before workspace, branch, or state
  mutation. GC never consumes the ordinary lossy normalized state view for
  this decision.
- **Residual proof-to-delete race:** the predicate re-reads a clean, unchanged
  HEAD immediately before authorizing collection, but that read and the later
  filesystem/git deletion are not one atomic operation. Existing active,
  pipeline, retry-window, minimum-age, and stop gates make a concurrent writer
  in this interval abnormal. Eliminating the interval entirely requires a
  shared workspace ownership lock spanning every writer and GC implementation.

## Alternatives considered

- **GC at merge-path only.** Already the first line of defense, but does not cover manual merges, HITL closures, or crash-mid-cleanup.
- **Cron script outside the orchestrator.** Possible but adds an out-of-process dependency; the orchestrator already has the state context needed to decide what's safe to GC.

## Related

- `src/workspace_gc_loop.py:WorkspaceGCLoop`
- `src/ports.py:WorkspacePort`, `src/ports.py:PRPort`
- [ADR-0003](0003-git-worktrees-for-isolation.md) — Git Worktrees for Issue Isolation
- [ADR-0029](0029-caretaker-loop-pattern.md) — Caretaker Background Loop Pattern
