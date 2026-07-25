---
id: 0769
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T01:13:09.867451+00:00
status: active
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
---

# Run full make quality, not a file-targeted pytest subset, before done

Always run the full `make quality` gate — never a file-targeted `pytest` subset — before declaring a task complete, especially for predicate-extraction or cleanup changes touching widely-used code like `_is_eligible` in `src/issue_store.py`.

Example: PR #8460 pruned defensive `getattr(self, "_X", None)` guards, ran 211 tests across three targeted files (all green), and shipped — but `make quality` would have caught 7 failures in `tests/test_audit_prompts.py` and `tests/test_repo_wiki_loop_pr.py`, requiring hotfix PR #8463.

**Why:** Targeted-file test runs give false confidence; changes to widely-used predicates have blast radius beyond the files they directly touch.
