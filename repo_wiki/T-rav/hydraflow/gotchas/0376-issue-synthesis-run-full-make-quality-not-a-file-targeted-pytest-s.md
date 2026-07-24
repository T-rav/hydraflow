---
id: 0376
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:12:12.384010+00:00
status: superseded
corroborations: 1
supersedes: 0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369
superseded_by: 0402
---

# Run full make quality, not a file-targeted pytest subset, before done

Always run the full `make quality` gate — never a file-targeted `pytest` subset — before declaring a task complete, especially for predicate-extraction or cleanup changes touching widely-used code like `_is_eligible` in `src/issue_store.py`.

Example: PR #8460 pruned defensive `getattr(self, "_X", None)` guards, ran 211 tests across three targeted files (all green), and shipped — but `make quality` would have caught 7 failures in `tests/test_audit_prompts.py` and `tests/test_repo_wiki_loop_pr.py`, requiring hotfix PR #8463.

**Why:** Targeted-file test runs give false confidence; changes to widely-used predicates have blast radius beyond the files they directly touch.
