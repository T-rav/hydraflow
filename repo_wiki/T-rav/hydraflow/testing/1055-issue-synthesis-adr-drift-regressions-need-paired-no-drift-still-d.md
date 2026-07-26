---
id: 1055
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.523670+00:00
status: superseded
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
superseded_by: 1085
---

# ADR drift regressions need paired no-drift + still-drifts checks

When adding a tests/test_adr_drift.py regression for a citation fix, assert both directions: (1) a compute_drift run over a PR touching only the file (no symbol evidence) yields zero findings for that ADR, mirroring test_real_adrs_do_not_drift_on_dependency_only_touches; (2) a diff naming the qualified symbol still drifts, mirroring test_symbol_citation_of_pr_manager_still_drifts. Only the first assertion risks over-suppressing real regressions.

**Why:** a one-sided test (only checking no-drift) can't catch coverage being accidentally suppressed for genuine changes to the cited method.
