---
id: 0668
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:31:08.513970+00:00
status: superseded
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631
superseded_by: 0672
---

# Cleanup/consolidation PRs require full `make quality`, not a targeted subset

For the `src/jsonl_ledger.py` unification (#10403), the plan required full `make quality` (ruff, pyright, tests, jscpd) rather than only `tests/test_escape_ledger.py` / `tests/test_intervention_tally.py` / `tests/test_erosion_trends.py` in isolation, plus added `tests/test_audit_sample_store.py` since `AuditSampleLedger` had only indirect coverage. The same requirement applied to the #10411 ADR-drift fan-out suppression feature, over targeted runs of `tests/test_adr_drift.py` / `tests/test_adr_touchpoint_auditor_loop.py` / `tests/test_adr_drift_resolver_loop.py` — an existing direct-call drift test could bare-cite a file by ≥`adr_drift_shared_infra_fanout_threshold` ADRs and expect drift, which the new suppression flips to non-drift.

**Why:** mirrors the PR #8460/#8463 lesson in CLAUDE.md — file-targeted subsets pass green while a full-suite regression hides elsewhere.
