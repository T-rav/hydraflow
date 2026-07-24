---
id: 0887
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:22:24.563429+00:00
status: superseded
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
superseded_by: 0896
---

# ADR drift regressions need paired no-drift + still-drifts checks

When adding a `tests/test_adr_drift.py` regression for a citation fix, assert both directions: (1) a `compute_drift` run over a PR touching only the file (no symbol evidence) yields zero findings for that ADR, mirroring `test_real_adrs_do_not_drift_on_dependency_only_touches`; (2) a diff naming the qualified symbol still drifts, mirroring `test_symbol_citation_of_pr_manager_still_drifts`. Only the first assertion risks over-suppressing real regressions.

**Why:** a one-sided test (only checking no-drift) can't catch coverage being accidentally suppressed for genuine changes to the cited method.
