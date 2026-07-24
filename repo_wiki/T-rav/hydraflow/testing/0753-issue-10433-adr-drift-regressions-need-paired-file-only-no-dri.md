---
id: 0753
topic: testing
source_issue: 10433
source_phase: plan
created_at: 2026-07-24T10:22:54.781365+00:00
status: active
corroborations: 1
---

# ADR drift regressions need paired file-only-no-drift + symbol-still-drifts assertions

When adding a `tests/test_adr_drift.py` regression for a citation fix, assert both directions: (1) a `compute_drift` run over a PR touching only the file (no symbol evidence) yields zero findings for that ADR, mirroring `test_real_adrs_do_not_drift_on_dependency_only_touches`; (2) a diff naming the qualified symbol still drifts, mirroring `test_symbol_citation_of_pr_manager_still_drifts`. Only the first assertion risks over-suppressing real regressions.

**Why:** a one-sided test (only checking no-drift) can't catch coverage being accidentally suppressed for genuine changes to the cited method.
