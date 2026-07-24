---
id: 0832
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:43:21.211244+00:00
status: superseded
corroborations: 1
supersedes: 0754,0755,0756,0757,0758,0759,0760,0761,0762,0763,0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797
superseded_by: 0847
---

# ADR drift regressions must drive the real docs/adr tree, not fixtures

Regression tests for ADR citation/drift bugs should drive the actual `docs/adr/` directory through `ADRIndex` and `compute_drift` (per `src/adr_drift.py` + `src/adr_index.py`), asserting on real parsed `source_symbols` and zero findings for a file-only diff — not a synthetic mock ADR.

Example: both `tests/regressions/test_issue_10384.py` and `tests/regressions/test_issue_10411.py` follow this pattern, importing `compute_drift`/`ADRIndex` directly and asserting on real `source_symbols[...]` output for the actual ADR file. See also: Test drift-suppression logic with synthetic ADR fixtures in unit tests, which covers unit tests of the drift mechanism itself instead.

**Why:** a fixture-only test can pass even if the live ADR file regresses to a bare citation, silently reopening the same rollup.
