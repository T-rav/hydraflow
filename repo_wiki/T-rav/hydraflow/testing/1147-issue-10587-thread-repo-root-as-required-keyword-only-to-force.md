---
id: 1147
topic: testing
source_issue: 10587
source_phase: plan
created_at: 2026-07-26T02:52:52.792532+00:00
status: superseded
corroborations: 1
superseded_by: 1154
---

# Thread repo_root as required keyword-only to force worktree wiring

When adding `repo_root` to `RepoWikiLoop._lint_and_compile_repos` (src/repo_wiki_loop.py) to support the shipped-claim exemption, make it a **required** keyword-only param, not one defaulting to `None`. `active_lint_tracked` itself can default `repo_root=None` (falls back to `tracked_root.parent`) for backward compat with 15 existing call sites, but the loop-level call must pass `repo_root=worktree` explicitly.
**Why:** if every layer defaults to `None`, the exemption silently never fires in production even though all unit tests pass against the default fallback — a known pre-mortem risk class ("silent no-op in prod") for this codebase's optional-param plumbing.
