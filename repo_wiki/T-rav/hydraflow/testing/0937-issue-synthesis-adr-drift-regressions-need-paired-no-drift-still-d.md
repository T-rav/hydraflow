---
id: 0937
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T23:41:31.214148+00:00
status: active
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
---

# ADR drift regressions need paired no-drift + still-drifts checks

When adding a `tests/test_adr_drift.py` regression for a citation fix, assert both directions: (1) a `compute_drift` run over a PR touching only the file (no symbol evidence) yields zero findings for that ADR, mirroring `test_real_adrs_do_not_drift_on_dependency_only_touches`; (2) a diff naming the qualified symbol still drifts, mirroring `test_symbol_citation_of_pr_manager_still_drifts`. Only the first assertion risks over-suppressing real regressions.

**Why:** a one-sided test (only checking no-drift) can't catch coverage being accidentally suppressed for genuine changes to the cited method.
