---
id: 2364
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.141200+00:00
status: superseded
corroborations: 1
supersedes: 2222
superseded_by: 2553
---

# Guard population definitions with set-wise regression tests

Use behavioral set-equality assertions, not count comparisons, when tying a derived population to its source filter.

Example: `tests/regressions/test_issue_10915.py` asserts `in_scope_adrs(corpus)` equals exactly the ADR set `evaluate_adrs` emits over a mixed-status synthetic corpus. Cite the containing function (`evaluate_adrs` in `src/adr_conformance.py`), not a bare line number.

**Why:** Count-based tests pass on compensating changes; set-wise comparison catches silent divergence between `setpoint.population` and `evaluate_adrs`.
