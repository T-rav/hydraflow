---
id: 0932
topic: gotchas
source_issue: 10530
source_phase: plan
created_at: 2026-07-25T09:44:02.075253+00:00
status: active
corroborations: 1
---

# ADR-drift right-sizing regression tests pin exact symbol owners

`tests/regressions/test_issue_9419_9421_adr_drift.py` maintains a `_RIGHT_SIZED` set and an `expected_symbol_owner` map that must be extended together whenever an ADR's citations are right-sized (e.g. adding entry `97` for ADR-0097). The test asserts the real `parse_adr_file` resolves each qualified citation to a symbol that actually exists on disk (e.g. `ImplementPhase._record_impl_metrics` at src/implement_phase.py:655) — a typo'd or renamed symbol would silently and permanently disable drift detection for that file with no error signal.

**Why:** guards against the top risk in this pattern — silent, undetectable suppression of legitimate drift via a wrong symbol name.
