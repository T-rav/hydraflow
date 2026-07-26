---
id: 0946
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:48:37.086799+00:00
status: active
corroborations: 1
supersedes: 0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895,0896,0897,0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0932,0933,0934,0935,0936,0937,0938,0939
---

# Run full make quality before done — never a file-targeted pytest subset

Always run the full `make quality` gate — never a file-targeted `pytest` subset — before declaring a task complete, especially for predicate-extraction or cleanup changes touching widely-used code.

Example: PR #8460 pruned defensive `getattr(self, "_X", None)` guards in `_is_eligible` (src/issue_store.py), ran 211 tests across three targeted files (all green), and shipped — but `make quality` would have caught 7 failures in `tests/test_audit_prompts.py`/`tests/test_repo_wiki_loop_pr.py`, requiring hotfix PR #8463. The `ADRCouncilReviewer` signature cleanup (issue #10524) applied the lesson directly, running full `make quality` instead of just the targeted ADR-reviewer test files.

**Why:** Targeted-file test runs give false confidence; changes to widely-used predicates or signatures have blast radius beyond the files they directly touch.
