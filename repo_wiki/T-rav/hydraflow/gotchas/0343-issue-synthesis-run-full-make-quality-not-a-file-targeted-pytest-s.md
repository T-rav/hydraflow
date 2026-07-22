---
id: 0343
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T17:02:49.507226+00:00
status: active
corroborations: 1
supersedes: 0327,0328,0329,0330,0331,0332,0333,0334,0335,0336
---

# Run full make quality, not a file-targeted pytest subset, before done

Always run the full `make quality` gate — never a file-targeted `pytest` subset — before declaring a task complete.

Example: PR #8460 ran 211 tests across three targeted files (all green) but shipped over-pruned defensive guards; `make quality` would have caught 7 failures in `tests/test_audit_prompts.py` and `tests/test_repo_wiki_loop_pr.py`.

**Why:** Targeted runs miss cross-module regressions; cleanup PRs have higher blast radius than their diffs suggest.
