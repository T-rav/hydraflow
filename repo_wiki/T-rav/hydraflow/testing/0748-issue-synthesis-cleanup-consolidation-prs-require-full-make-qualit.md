---
id: 0748
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.448415+00:00
status: active
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
---

# Cleanup/consolidation PRs require full `make quality`, not a targeted subset

Cleanup/consolidation PRs must run full `make quality` (ruff, pyright, tests, jscpd), not just the tests for directly-touched files.

Example: for the `src/jsonl_ledger.py` unification (#10403), full quality was required rather than only `tests/test_escape_ledger.py` / `test_intervention_tally.py` / `test_erosion_trends.py` in isolation, plus `tests/test_audit_sample_store.py` was added since `AuditSampleLedger` had only indirect coverage. Same for the #10411 ADR-drift fan-out suppression, over targeted runs of `test_adr_drift.py` / `test_adr_touchpoint_auditor_loop.py` / `test_adr_drift_resolver_loop.py` — an existing direct-call drift test could bare-cite a file by ≥`adr_drift_shared_infra_fanout_threshold` ADRs and expect drift, which the new suppression flips to non-drift.

**Why:** mirrors the PR #8460/#8463 lesson in CLAUDE.md — file-targeted subsets pass green while a full-suite regression hides elsewhere.
