# ADR-0112: Per-Issue Isolation via Local Git Clone

**Status:** Accepted
**Date:** 2026-07-26
**Enforcement:** enforced
**Enforced by:** pytest:tests/architecture/test_adr0112_clone_local_isolation.py::test_workspace_create_uses_git_clone_local
**Supersedes:** ADR-0003 (Git Worktrees for Issue Isolation)

## Context

ADR-0003 established that each issue is implemented in a filesystem-isolated
working tree, created with `git worktree add` at `../hydraflow-worktrees/issue-{number}/`,
sharing the primary repo's git object store. The **isolation decision** — one
independent working directory per in-flight issue, on its own branch, torn down
on merge/close — has held up well and is not in question here.

The **mechanism**, however, has since moved off `git worktree`. ADR-0003 itself
listed two negatives that pushed the change:

- **Open file handles prevent teardown.** A long-running implementation (an
  agent running tests, a container holding the tree open) keeps file handles
  open in the worktree, which makes `git worktree remove` fail mid-run. A
  linked worktree is not fully independent of the primary repo, so this
  contention is structural.
- **Docker-mount complexity.** Running an agent in a container requires mounting
  the worktree path in; a linked worktree's dependence on the primary `.git`
  (via its `.git` gitfile pointer and shared object store) makes that mount and
  its `core.worktree` bookkeeping fragile — the recurring stale-`core.worktree`
  corruption (`#9723`) is a direct symptom.

`git clone --local` sidesteps both. A local clone hardlinks the object store
(so it is still fast and cheap on disk — no redundant packing), but gives the
per-issue workspace a **fully independent** `.git/` directory with its own
`HEAD`, config, and remote. There is no shared-worktree bookkeeping to corrupt
and no linked-worktree handle contention on teardown: the workspace is just a
directory that can be `rmtree`'d. This is the mechanism
`src/workspace.py:WorkspaceManager` already ships — its `create` clones
locally; the `wt_path` and "worktree" names throughout the module are vestigial
labels for what are now full local clones.

Because this changes the isolation *mechanism* named in ADR-0003's Decision
(not merely its Consequences), it is recorded as a superseding decision rather
than a clarification, per the repo's ADR discipline.

## Decision

Create the per-issue workspace as an **independent local git clone**, not a
linked git worktree.

- `WorkspaceManager.create` (`src/workspace.py:WorkspaceManager.create`) acquires
  a per-repo workspace lock and delegates to
  `src/workspace.py:WorkspaceManager._create_unlocked`, which runs
  `git clone --local --no-checkout <primary-checkout> <workspace-path>`. The
  `--local` flag hardlinks the object store (fast, no extra disk); the clone
  gets its own `.git/`, so it is independent of the primary checkout.
- The clone's `origin` is then repointed at the real GitHub remote (the clone
  initially points at the local path), latest state is fetched, and the
  issue branch is created from the base branch — or checked out if it already
  exists on the remote (resumable work). Branch-per-issue is unchanged.
- The workspace lives at a **repo-slug-scoped isolated path**,
  `src/config.py:HydraFlowConfig.workspace_path_for_issue`
  (`workspace_base/<repo-slug>/issue-{number}`), so concurrent issues — and
  multiple repos in multi-repo mode — never collide and are always distinct
  from the primary checkout.
- The workspace is destroyed (a plain directory removal) after the PR merges or
  the issue closes, reaped by the workspace GC loop.

The formal interface remains `src/ports.py:WorkspacePort`.

## Consequences

**Positive:**

- Full independence: the per-issue clone has its own `.git/`, so teardown is a
  directory removal that never contends with open handles, and there is no
  linked-worktree `core.worktree` state to go stale under docker mounts.
- Still cheap: `--local` hardlinks objects, so a clone is fast and adds no
  redundant object storage versus the old shared-store worktree.
- Docker-friendly: an independent clone mounts into a container cleanly without
  the primary repo's worktree bookkeeping riding along.
- Parallelism and branch-per-issue are preserved exactly as ADR-0003 intended.

**Negative / Trade-offs:**

- The `wt_path` / "worktree" naming in `src/workspace.py` is now a misnomer for
  a local clone; the vestigial names are kept to bound the diff but can mislead
  a reader who takes them literally.
- A local clone still needs write access under `workspace_base`; the isolated
  path is repo-slug-scoped rather than a fixed `../hydraflow-worktrees/` sibling.
- Hardlinked objects share inodes with the primary store, so a filesystem that
  cannot hardlink across the relevant boundary falls back to a full copy (git's
  own behavior), which is slower but still correct.

## Related

- ADR-0003 (Git Worktrees for Issue Isolation) — **superseded by this ADR**; the
  isolation decision is retained, the `git worktree add` mechanism is replaced.
- ADR-0001 (Five Concurrent Async Loops) — the concurrency model that makes
  per-issue isolated workspaces necessary.
- ADR-0006 (RepoRuntime Isolation Architecture) — repo-level isolation that the
  repo-slug-scoped workspace path composes with in multi-repo mode.
- `src/workspace.py:WorkspaceManager.create` — public entry point.
- `src/workspace.py:WorkspaceManager._create_unlocked` — the `git clone --local
  --no-checkout` implementation.
- `src/config.py:HydraFlowConfig.workspace_path_for_issue` — the repo-slug-scoped
  workspace path.
- `src/ports.py:WorkspacePort` — the formal interface.
