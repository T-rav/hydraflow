# Proposal: stop the maintenance loops from leaving `repo_root` dirty

**Status:** Draft / for review (do not merge as-is — this is the design, not the change)
**Context:** Part 3 of 3 on factory working-tree hygiene. Parts 1 & 2 (untrack
runtime caches #9537; `make factory` isolated workspace #9538) already remove the
operator pain. This documents the *source-level* fix and why the obvious versions
are wrong, so we implement the right one deliberately.

## Root cause

Eight loops generate artifacts by **mutating tracked files in `config.repo_root`**
(the checkout the server runs from) and then PR those diffs:

`diagram_loop`, `contract_refresh_loop`, `pricing_refresh_loop`,
`term_proposer_runtime`, `repo_wiki_loop`, `corpus_learning_loop`,
`service_registry` (wiki bootstrap), `adr_reviewer`.

Each opens its PR via `auto_pr.open_automated_pr_async`, which builds the commit
in an **ephemeral worktree branched off `origin/<base>`**, then deletes it. It
reads the file *contents* from `repo_root` but **never restores the originals
there** — so the working tree is left dirty. The runtime caches (now untracked in
#9537) churned every tick and made this constant; the remaining wiki/arch
artifacts dirty the tree during each maintenance cycle.

## Why the obvious fixes are wrong

1. **Restore `repo_root` to HEAD right after opening the PR.**
   The loops detect "a PR is already open" via in-memory state and *coalesce*
   (append) rather than re-open. If we restore after opening, the next tick
   regenerates the same diffs → coalesce → **a new commit appended to the
   maintenance PR every tick**. PR bloat; never settles. ❌

2. **Restore `repo_root` to the merged base after the loop merges its PR.**
   The loops PR to `base_branch()` = **staging**, but the factory runs on
   **main**. After the PR merges to staging, the content lives on
   `origin/staging`; `repo_root` (on main) still differs until the staging→main
   RC promotion. So a `main` checkout **cannot be made clean** by a post-merge
   restore — the diff is real (main genuinely lacks the staging content yet). ❌

## The correct fix

**Generate inside the ephemeral worktree, never touch `repo_root`.** Each loop's
lint/compile/regen step should run against the worktree `auto_pr` already creates
off `origin/<base>`, so the diff is computed and committed there and `repo_root`
is never mutated.

Concretely:
- Extend `auto_pr` with a "generate-then-PR" entry point that creates the
  worktree first, hands the loop a path to operate in, then commits/pushes/PRs
  what changed — replacing the current "mutate repo_root → pass file list" shape.
- Migrate callers incrementally, **`repo_wiki_loop` first** (highest churn): move
  `active_lint_tracked` + topic compile to operate on the worktree's
  `repo_wiki/` + `docs/wiki/` instead of `repo_root`'s.
- Keep a regression test per migrated loop: run a full generate→PR cycle and
  assert `git status --porcelain` in `repo_root` is empty afterward.

This is correct regardless of the main-vs-staging gap because `repo_root` is
never written.

## Recommendation / sequencing

1. **Now:** adopt `make factory` (#9538) as the operator path — the dev checkout
   is never touched, which fully resolves the reported pain. The isolated
   workspace also hard-resets to base each launch, so any within-run churn is
   discarded between runs.
2. **Optional, low-cost:** default `HYDRAFLOW_FACTORY_BRANCH` to the active base
   (`staging`) so the factory runs the branch it PRs to — then a post-merge
   `git pull` in the workspace converges cleanly (option 2 becomes viable there).
3. **Follow-up refactor (this proposal):** implement "generate-in-worktree",
   `repo_wiki_loop` first, then the other seven callers. Scoped, TDD'd, one PR
   per loop.

Until the refactor lands, #9537 + #9538 are the supported answer.
