---
id: 0881
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T15:47:47.994626+00:00
status: active
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
---

# ADR drift regressions must drive the real docs/adr tree, not fixtures

Regression tests for ADR citation/drift bugs should drive the actual `docs/adr/` directory through `ADRIndex` and `compute_drift` (per `src/adr_drift.py` + `src/adr_index.py`), asserting on real parsed `source_symbols` and zero findings for a file-only diff — not a synthetic mock ADR.

Example: both `tests/regressions/test_issue_10384.py` and `tests/regressions/test_issue_10411.py` follow this pattern, importing `compute_drift`/`ADRIndex` directly and asserting on real `source_symbols[...]` output for the actual ADR file. See also: Test drift-suppression logic with synthetic ADR fixtures in unit tests, which covers unit tests of the drift mechanism itself instead.

**Why:** a fixture-only test can pass even if the live ADR file regresses to a bare citation, silently reopening the same rollup.
