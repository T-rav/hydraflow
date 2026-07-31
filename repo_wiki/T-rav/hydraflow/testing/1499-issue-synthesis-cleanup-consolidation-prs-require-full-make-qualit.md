---
id: 1499
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T19:46:33.742961+00:00
status: superseded
corroborations: 1
supersedes: 1411
superseded_by: 1581
---

# Cleanup/consolidation PRs require full make quality

Cleanup/consolidation/refactor PRs touching multiple modules must run full make quality (ruff, pyright, tests, jscpd), never a file-targeted pytest subset.

Example: PR #8460 shipped after a 211-test targeted-file pass went green, but tests/test_audit_prompts.py and tests/test_repo_wiki_loop_pr.py had 7 failures the subset missed, forcing hotfix PR #8463.

**Why:** Cross-module refactors have wider blast radius than their diff — a targeted subset silently misses affected files outside the diff.
