---
id: 0708
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.888024+00:00
status: superseded
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
superseded_by: 0712
---

# Cleanup/consolidation PRs require full `make quality`, not a targeted subset

Cleanup/consolidation PRs must run full `make quality` (ruff, pyright, tests, jscpd), not just the tests for directly-touched files.

Example: for the `src/jsonl_ledger.py` unification (#10403), full quality was required rather than only `tests/test_escape_ledger.py` / `test_intervention_tally.py` / `test_erosion_trends.py` in isolation, plus `tests/test_audit_sample_store.py` was added since `AuditSampleLedger` had only indirect coverage. Same for the #10411 ADR-drift fan-out suppression, over targeted runs of `test_adr_drift.py` / `test_adr_touchpoint_auditor_loop.py` / `test_adr_drift_resolver_loop.py` — an existing direct-call drift test could bare-cite a file by ≥`adr_drift_shared_infra_fanout_threshold` ADRs and expect drift, which the new suppression flips to non-drift.

**Why:** mirrors the PR #8460/#8463 lesson in CLAUDE.md — file-targeted subsets pass green while a full-suite regression hides elsewhere.
