---
id: 0788
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:12:20.356038+00:00
status: active
corroborations: 1
supersedes: 0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753
---

# ADR drift regressions must drive the real docs/adr tree, not fixtures

Regression tests for ADR citation/drift bugs should drive the actual `docs/adr/` directory through `ADRIndex` and `compute_drift` (per `src/adr_drift.py` + `src/adr_index.py`), asserting on real parsed `source_symbols` and zero findings for a file-only diff — not a synthetic mock ADR.

Example: both `tests/regressions/test_issue_10384.py` and `tests/regressions/test_issue_10411.py` follow this pattern, importing `compute_drift`/`ADRIndex` directly and asserting on real `source_symbols[...]` output for the actual ADR file. See also: Test drift-suppression logic with synthetic ADR fixtures in unit tests, which covers unit tests of the drift mechanism itself instead.

**Why:** a fixture-only test can pass even if the live ADR file regresses to a bare citation, silently reopening the same rollup.
