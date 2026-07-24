---
id: 0354
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T18:02:32.384107+00:00
status: superseded
corroborations: 1
supersedes: 0337,0338,0339,0340,0341,0342,0343,0344,0345,0346,0347
superseded_by: 0370
---

# Run full make quality, not a file-targeted pytest subset, before done

Always run the full `make quality` gate — never a file-targeted `pytest` subset — before declaring a task complete.

Example: PR #8460 ran 211 tests across three targeted files (all green) but shipped over-pruned defensive guards; `make quality` would have caught 7 failures in `tests/test_audit_prompts.py` and `tests/test_repo_wiki_loop_pr.py`.

**Why:** Targeted runs miss cross-module regressions; cleanup PRs have higher blast radius than their diffs suggest.
