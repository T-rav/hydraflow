---
id: 0838
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:43:21.218855+00:00
status: active
corroborations: 1
supersedes: 0754,0755,0756,0757,0758,0759,0760,0761,0762,0763,0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797
---

# ADR drift regressions need paired no-drift + still-drifts checks

When adding a `tests/test_adr_drift.py` regression for a citation fix, assert both directions: (1) a `compute_drift` run over a PR touching only the file (no symbol evidence) yields zero findings for that ADR, mirroring `test_real_adrs_do_not_drift_on_dependency_only_touches`; (2) a diff naming the qualified symbol still drifts, mirroring `test_symbol_citation_of_pr_manager_still_drifts`. Only the first assertion risks over-suppressing real regressions.

**Why:** a one-sided test (only checking no-drift) can't catch coverage being accidentally suppressed for genuine changes to the cited method.
