---
id: 0500
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.774662+00:00
status: superseded
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
superseded_by: 0545
---

# Run full make quality, not a file-targeted pytest subset, before done

Always run the full `make quality` gate — never a file-targeted `pytest` subset — before declaring a task complete, especially for predicate-extraction or cleanup changes touching widely-used code like `_is_eligible` in `src/issue_store.py`.

Example: PR #8460 pruned defensive `getattr(self, "_X", None)` guards, ran 211 tests across three targeted files (all green), and shipped — but `make quality` would have caught 7 failures in `tests/test_audit_prompts.py` and `tests/test_repo_wiki_loop_pr.py`, requiring hotfix PR #8463.

**Why:** Targeted-file test runs give false confidence; changes to widely-used predicates have blast radius beyond the files they directly touch.
