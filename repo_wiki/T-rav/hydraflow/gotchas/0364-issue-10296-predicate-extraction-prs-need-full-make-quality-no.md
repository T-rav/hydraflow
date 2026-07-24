---
id: 0364
topic: gotchas
source_issue: 10296
source_phase: plan
created_at: 2026-07-22T17:44:18.122256+00:00
status: superseded
corroborations: 1
superseded_by: 0370
---

# Predicate-extraction PRs need full make quality, not targeted test subsets (#8460 lesson)

Any change that extracts logic out of a widely-used predicate (like `_is_eligible` in `src/issue_store.py`) has blast radius beyond the files it directly touches — gate it with full `make quality`, not `pytest tests/test_issue_store.py` alone.

PR #8460 pruned defensive `getattr(self, "_X", None)` guards, ran 211 tests across three targeted files (all green), and shipped — but `tests/test_audit_prompts.py` and `tests/test_repo_wiki_loop_pr.py` had 7 failures the subset missed, requiring hotfix PR #8463.

**Why:** targeted-file test runs give false confidence on changes whose real impact surface is repo-wide.
