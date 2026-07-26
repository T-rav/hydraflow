---
id: 0990
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.584230+00:00
status: superseded
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
superseded_by: 1015
---

# Cleanup/consolidation PRs require full `make quality`, not a targeted subset

Cleanup/consolidation/refactor PRs touching multiple modules must run full make quality (ruff, pyright, tests, jscpd), never a file-targeted pytest subset.

Example: the src/jsonl_ledger.py unification (#10403) required full quality rather than only the three directly-touched ledger test files — tests/test_audit_sample_store.py was added since AuditSampleLedger had only indirect coverage. The same standard applied to the #10411 ADR-drift fan-out suppression and the ledger-subclass refactor across src/audit/store.py, src/escape/ledger.py, src/intervention/ledger.py, src/erosion/trends.py.

**Why:** PR #8460 shipped after a 211-test targeted-file pass went green, but tests/test_audit_prompts.py and tests/test_repo_wiki_loop_pr.py had 7 failures the subset missed, forcing hotfix PR #8463 — cross-module refactors have wider blast radius than their diff.
