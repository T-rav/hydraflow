---
id: 0834
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:43:21.214059+00:00
status: active
corroborations: 1
supersedes: 0754,0755,0756,0757,0758,0759,0760,0761,0762,0763,0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797
---

# Cleanup/consolidation PRs require full `make quality`, not a targeted subset

Cleanup/consolidation PRs must run full `make quality` (ruff, pyright, tests, jscpd), not just the tests for directly-touched files.

Example: for the `src/jsonl_ledger.py` unification (#10403), full quality was required rather than only `tests/test_escape_ledger.py` / `test_intervention_tally.py` / `test_erosion_trends.py` in isolation, plus `tests/test_audit_sample_store.py` was added since `AuditSampleLedger` had only indirect coverage. Same for the #10411 ADR-drift fan-out suppression, over targeted runs of `test_adr_drift.py` / `test_adr_touchpoint_auditor_loop.py` / `test_adr_drift_resolver_loop.py` — an existing direct-call drift test could bare-cite a file by ≥`adr_drift_shared_infra_fanout_threshold` ADRs and expect drift, which the new suppression flips to non-drift.

**Why:** mirrors the PR #8460/#8463 lesson in CLAUDE.md — file-targeted subsets pass green while a full-suite regression hides elsewhere.
