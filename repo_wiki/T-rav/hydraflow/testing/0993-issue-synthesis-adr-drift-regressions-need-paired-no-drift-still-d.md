---
id: 0993
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T06:21:18.136443+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0951,0952
---

# ADR drift regressions need paired no-drift + still-drifts checks

When adding a `tests/test_adr_drift.py` regression for a citation fix, assert both directions: (1) a `compute_drift` run over a PR touching only the file (no symbol evidence) yields zero findings for that ADR, mirroring `test_real_adrs_do_not_drift_on_dependency_only_touches`; (2) a diff naming the qualified symbol still drifts, mirroring `test_symbol_citation_of_pr_manager_still_drifts`. Only the first assertion risks over-suppressing real regressions.

**Why:** a one-sided test (only checking no-drift) can't catch coverage being accidentally suppressed for genuine changes to the cited method.
