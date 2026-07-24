---
id: 0790
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:12:20.362116+00:00
status: superseded
corroborations: 1
supersedes: 0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753
superseded_by: 0798
---

# Cleanup/consolidation PRs require full `make quality`, not a targeted subset

Cleanup/consolidation PRs must run full `make quality` (ruff, pyright, tests, jscpd), not just the tests for directly-touched files.

Example: for the `src/jsonl_ledger.py` unification (#10403), full quality was required rather than only `tests/test_escape_ledger.py` / `test_intervention_tally.py` / `test_erosion_trends.py` in isolation, plus `tests/test_audit_sample_store.py` was added since `AuditSampleLedger` had only indirect coverage. Same for the #10411 ADR-drift fan-out suppression, over targeted runs of `test_adr_drift.py` / `test_adr_touchpoint_auditor_loop.py` / `test_adr_drift_resolver_loop.py` — an existing direct-call drift test could bare-cite a file by ≥`adr_drift_shared_infra_fanout_threshold` ADRs and expect drift, which the new suppression flips to non-drift.

**Why:** mirrors the PR #8460/#8463 lesson in CLAUDE.md — file-targeted subsets pass green while a full-suite regression hides elsewhere.
