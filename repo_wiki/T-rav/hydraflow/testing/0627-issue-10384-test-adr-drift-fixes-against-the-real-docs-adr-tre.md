---
id: 0627
topic: testing
source_issue: 10384
source_phase: plan
created_at: 2026-07-24T04:55:51.365329+00:00
status: active
corroborations: 1
---

# Test ADR drift fixes against the real docs/adr tree via ADRIndex/compute_drift, not fixtures

Regression tests for ADR citation/drift bugs (e.g. `tests/regressions/test_issue_10384.py`) should drive the actual `docs/adr/` directory through `ADRIndex` and `compute_drift` (per `src/adr_drift.py` + `src/adr_index.py`), asserting on real parsed `source_symbols` and zero findings for a file-only diff — not a synthetic mock ADR. This catches both parser regressions and doc-content regressions (e.g. someone re-introducing a bare citation) in one test.

**Why:** a fixture-only test can pass even if the live ADR file regresses to a bare citation, silently reopening the same rollup.
