---
id: 1786
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T04:20:59.106739+00:00
status: superseded
corroborations: 1
supersedes: 1692
superseded_by: 1891
---

# Thread repo_root as required keyword-only for worktree wiring

When adding `repo_root` to RepoWikiLoop._lint_and_compile_repos (src/repo_wiki_loop.py), make it a required keyword-only param, not one defaulting to None.

Example: active_lint_tracked can default repo_root=None for backward compat with 15 existing call sites, but the loop-level call must pass repo_root=worktree explicitly.

**Why:** If every layer defaults to None, the exemption silently never fires in production even though all unit tests pass against the default fallback.
