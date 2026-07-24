---
id: 0631
topic: testing
source_issue: 10411
source_phase: plan
created_at: 2026-07-24T05:57:06.014408+00:00
status: active
corroborations: 1
---

# ADR-drift feature closes with full `make quality`, not targeted test files, per cleanup-blast-radius rule

The #10411 plan explicitly calls out running full `make quality` before merge — not just `tests/test_adr_drift.py`/`tests/test_adr_touchpoint_auditor_loop.py`/`tests/test_adr_drift_resolver_loop.py` — because an existing direct-call drift test could bare-cite a file by ≥`adr_drift_shared_infra_fanout_threshold` ADRs and expect drift, which the new fan-out suppression would flip to non-drift. **Why:** mirrors the PR #8460/#8463 lesson in CLAUDE.md — file-targeted subsets green while a full-suite regression hides elsewhere.
