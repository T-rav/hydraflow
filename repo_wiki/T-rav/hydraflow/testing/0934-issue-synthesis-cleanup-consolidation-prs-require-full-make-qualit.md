---
id: 0934
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:46:40.917797+00:00
status: superseded
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
superseded_by: 0953
---

# Cleanup/consolidation PRs require full `make quality`, not a targeted subset

Cleanup/consolidation/refactor PRs touching multiple modules must run full `make quality` (ruff, pyright, tests, jscpd), never a file-targeted pytest subset.

Example: the `src/jsonl_ledger.py` unification (#10403) required full quality rather than only the three directly-touched ledger test files — `tests/test_audit_sample_store.py` was added since `AuditSampleLedger` had only indirect coverage. The same standard applied to the #10411 ADR-drift fan-out suppression and the ledger-subclass refactor across `src/audit/store.py`, `src/escape/ledger.py`, `src/intervention/ledger.py`, `src/erosion/trends.py`.

**Why:** PR #8460 shipped after a 211-test targeted-file pass went green, but `tests/test_audit_prompts.py` and `tests/test_repo_wiki_loop_pr.py` had 7 failures the subset missed, forcing hotfix PR #8463 — cross-module refactors have wider blast radius than their diff.
