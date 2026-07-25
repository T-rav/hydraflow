---
id: 0932
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:46:40.911244+00:00
status: superseded
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
superseded_by: 0954
---

# ADR drift regressions must drive the real docs/adr tree, not fixtures

Regression tests for ADR citation/drift bugs should drive the actual `docs/adr/` directory through `ADRIndex` and `compute_drift` (per `src/adr_drift.py` + `src/adr_index.py`), asserting on real parsed `source_symbols` and zero findings for a file-only diff — not a synthetic mock ADR.

Example: both `tests/regressions/test_issue_10384.py` and `tests/regressions/test_issue_10411.py` follow this pattern, importing `compute_drift`/`ADRIndex` directly and asserting on real `source_symbols[...]` output for the actual ADR file. See also: Test drift-suppression logic with synthetic ADR fixtures in unit tests, which covers unit tests of the drift mechanism itself instead.

**Why:** a fixture-only test can pass even if the live ADR file regresses to a bare citation, silently reopening the same rollup.
