---
id: 2222
topic: testing
source_issue: 10915
source_phase: plan
created_at: 2026-07-31T15:36:39.647816+00:00
status: superseded
corroborations: 1
superseded_by: 2364
---

# Guard population definitions with set-wise regression tests

Use behavioral set-equality assertions, not count comparisons, when tying a derived population to its source filter.

- `tests/regressions/test_issue_10915.py` asserts `in_scope_adrs(corpus)` equals exactly the ADR set `evaluate_adrs` emits over a mixed-status synthetic corpus.
- Cite the containing function (`evaluate_adrs` in `src/adr_conformance.py`), not a bare line number — line 498 will move.

**Why:** Count-based tests pass on compensating changes (e.g., a status filter added to one path but not the other); set-wise comparison catches silent divergence between `setpoint.population` and `evaluate_adrs`.
