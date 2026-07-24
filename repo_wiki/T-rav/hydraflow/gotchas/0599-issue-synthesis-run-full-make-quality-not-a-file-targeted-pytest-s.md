---
id: 0599
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:27.955809+00:00
status: active
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
---

# Run full make quality, not a file-targeted pytest subset, before done

Always run the full `make quality` gate — never a file-targeted `pytest` subset — before declaring a task complete, especially for predicate-extraction or cleanup changes touching widely-used code like `_is_eligible` in `src/issue_store.py`.

Example: PR #8460 pruned defensive `getattr(self, "_X", None)` guards, ran 211 tests across three targeted files (all green), and shipped — but `make quality` would have caught 7 failures in `tests/test_audit_prompts.py` and `tests/test_repo_wiki_loop_pr.py`, requiring hotfix PR #8463.

**Why:** Targeted-file test runs give false confidence; changes to widely-used predicates have blast radius beyond the files they directly touch.
