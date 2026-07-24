---
id: 0189
topic: architecture
source_issue: 10443
source_phase: plan
created_at: 2026-07-24T11:10:04.090326+00:00
status: active
corroborations: 1
---

# ADR-drift regression tests should self-retire, not stub ADRIndex

Regression tests for citation/drift bugs (e.g. `tests/regressions/test_issue_10443.py`) should drive the real `docs/adr` directory and production `adr_index.ADRIndex` / `adr_drift.compute_drift_by_adr` — no mocks — and return early if the target ADR is later removed, renumbered, or leaves Accepted status. Import `_SHARED_INFRA_MODULES` directly from `src/adr_drift.py` rather than adding an accessor, matching sibling regressions for issues 10437/10441/9176. **Why:** keeps the growing family of ADR-drift regression tests (10408/10411/10413/10437/10440/10441/10443) from going brittle against routine ADR renumbering.
