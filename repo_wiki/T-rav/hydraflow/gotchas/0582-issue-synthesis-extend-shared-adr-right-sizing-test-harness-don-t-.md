---
id: 0582
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:39:28.222238+00:00
status: active
corroborations: 1
supersedes: 0494,0495,0496,0497,0498,0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539
---

# Extend shared ADR right-sizing test harness, don't fork a new file

When adding a new right-sized ADR citation (e.g. ADR-0012), extend the existing `_RIGHT_SIZED` list and `expected_symbol_owner` dict in `tests/regressions/test_issue_9419_9421_adr_drift.py` rather than writing a new test file or helper.

Example: this harness drives the real `adr_index.parse_adr_file` + `adr_drift.compute_drift` against actual ADR text, so it validates production parsing behavior, not a mock.

**Why:** Duplicating harnesses per-ADR was flagged as a gotchas-audit risk (conftest duplication); the shared parametrized table is the established pattern for this drift-fix class.
