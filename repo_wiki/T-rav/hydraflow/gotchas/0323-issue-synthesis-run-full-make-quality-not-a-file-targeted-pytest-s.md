---
id: 0323
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T13:38:34.196196+00:00
status: superseded
corroborations: 1
supersedes: 0310,0310,0311,0311,0312,0312,0313,0314,0315,0316
superseded_by: 0327
---

# Run full make quality, not a file-targeted pytest subset, before done

Always run the full `make quality` gate — never a file-targeted `pytest` subset — before declaring a task complete.

Example: PR #8460 ran 211 tests across three targeted files (all green) but shipped over-pruned defensive guards; `make quality` would have caught 7 failures in `tests/test_audit_prompts.py` and `tests/test_repo_wiki_loop_pr.py`.

**Why:** Targeted runs miss cross-module regressions; cleanup PRs have higher blast radius than their diffs suggest.
