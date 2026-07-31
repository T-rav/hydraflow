---
id: 2265
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:36.875882+00:00
status: active
corroborations: 1
supersedes: 2120
---

# Cross-module PRs require full make quality, not file-targeted

Cleanup, consolidation, refactor, and rename PRs touching multiple modules must run full `make quality` (ruff, pyright, tests, jscpd), never a file-targeted pytest subset.

Example: PR #8460 shipped after a 211-test targeted-file pass went green, but `tests/test_audit_prompts.py` and `tests/test_repo_wiki_loop_pr.py` had 7 failures the subset missed, forcing hotfix PR #8463.

**Why:** Cross-module changes have wider blast radius than their diff — a targeted subset silently misses affected files outside the diff.
