---
id: 0333
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T15:33:18.681197+00:00
status: active
corroborations: 1
supersedes: 0317,0318,0319,0320,0321,0322,0323,0324,0325,0326
---

# Run full make quality, not a file-targeted pytest subset, before done

Always run the full `make quality` gate — never a file-targeted `pytest` subset — before declaring a task complete.

Example: PR #8460 ran 211 tests across three targeted files (all green) but shipped over-pruned defensive guards; `make quality` would have caught 7 failures in `tests/test_audit_prompts.py` and `tests/test_repo_wiki_loop_pr.py`.

**Why:** Targeted runs miss cross-module regressions; cleanup PRs have higher blast radius than their diffs suggest.
