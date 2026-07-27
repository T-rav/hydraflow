---
id: 1216
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T18:41:12.927179+00:00
status: superseded
corroborations: 1
supersedes: 1147
superseded_by: 1290
---

# Thread repo_root as required keyword-only to force worktree wiring

When adding `repo_root` to `RepoWikiLoop._lint_and_compile_repos` (src/repo_wiki_loop.py) to support the shipped-claim exemption, make it a **required** keyword-only param, not one defaulting to `None`. `active_lint_tracked` itself can default `repo_root=None` (falls back to `tracked_root.parent`) for backward compat with 15 existing call sites, but the loop-level call must pass `repo_root=worktree` explicitly.

**Why:** if every layer defaults to `None`, the exemption silently never fires in production even though all unit tests pass against the default fallback — a known pre-mortem risk class for this codebase's optional-param plumbing.
