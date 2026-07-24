---
id: 0706
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.884297+00:00
status: superseded
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
superseded_by: 0712
---

# ADR drift regressions must drive the real docs/adr tree, not fixtures

Regression tests for ADR citation/drift bugs (e.g. `tests/regressions/test_issue_10384.py`) should drive the actual `docs/adr/` directory through `ADRIndex` and `compute_drift` (per `src/adr_drift.py` + `src/adr_index.py`), asserting on real parsed `source_symbols` and zero findings for a file-only diff — not a synthetic mock ADR.

Example: this applies to regression tests tied to a specific issue; see also: testing — Test drift-suppression logic with synthetic ADR fixtures in unit tests, which covers unit tests of the drift mechanism itself instead.

**Why:** a fixture-only test can pass even if the live ADR file regresses to a bare citation, silently reopening the same rollup.
