---
id: 1266
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T20:11:03.293732+00:00
status: active
corroborations: 1
supersedes: 1192
---

# ADR drift regressions need paired no-drift + still-drifts checks

When adding a tests/test_adr_drift.py regression for a citation fix, assert both directions: (1) a compute_drift run over a file-only diff yields zero findings for that ADR; (2) a diff naming the qualified symbol still drifts.

Example: mirror test_real_adrs_do_not_drift_on_dependency_only_touches and test_symbol_citation_of_pr_manager_still_drifts.

**Why:** A one-sided test (only checking no-drift) can't catch coverage being accidentally suppressed for genuine changes to the cited method.
