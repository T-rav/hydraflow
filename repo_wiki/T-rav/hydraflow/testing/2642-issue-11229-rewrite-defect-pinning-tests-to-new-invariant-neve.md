---
id: 2642
topic: testing
source_issue: 11229
source_phase: plan
created_at: 2026-08-15T07:12:37.006311+00:00
status: active
corroborations: 1
---

# Rewrite defect-pinning tests to new invariant; never loosen

When an existing test asserts the old defective behavior, rewrite it to express the new invariant. Do not loosen the assertion.

- `tests/test_escape_ledger_loop.py::TestMaxDiagnosesPerTick::test_diagnoser_is_bounded_by_the_diagnoses_cap` asserts `residue == eligible` — pinning the defect. The fix rewrites it to assert only attempted findings are filable; the disabled-config sibling stays as-is.

**Why:** Loosening the assertion ships a green suite over the same bug.
