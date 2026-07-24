---
id: 0441
topic: gotchas
source_issue: 10400
source_phase: plan
created_at: 2026-07-24T05:41:19.861289+00:00
status: active
corroborations: 1
---

# Reuse the parametrized harness in test_issue_9419_9421_adr_drift.py for new ADR right-sizing cases

When adding a new right-sized ADR citation (e.g. ADR-0012), extend the existing `_RIGHT_SIZED` list and `expected_symbol_owner` dict in `tests/regressions/test_issue_9419_9421_adr_drift.py` rather than writing a new test file or helper. This harness drives the real `adr_index.parse_adr_file` + `adr_drift.compute_drift` against actual ADR text, so it validates production parsing behavior, not a mock.

**Why:** Duplicating harnesses per-ADR was flagged as a gotchas-audit risk (conftest duplication); the shared parametrized table is the established pattern for this drift-fix class.
