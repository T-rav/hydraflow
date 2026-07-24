---
id: 0784
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:12:20.345877+00:00
status: superseded
corroborations: 1
supersedes: 0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753
superseded_by: 0798
---

# Test drift-suppression logic with synthetic ADR fixtures in unit tests

In `tests/test_adr_drift.py`, prove new citation-drift behavior (e.g. symbol-qualified citations suppressing drift on file-only touches) by driving `compute_drift`/`_citation_drifts` with a synthetic ADR object carrying the new citation form, plus a bare-citation case as a regression guard for existing behavior.

Example: pair with `tests/test_adr_index.py` assertions that `parse_adr_file` correctly parses the citation into `source_symbols`/`source_files`. This applies to unit tests of the drift *mechanism* itself — see also: ADR drift regressions must drive the real docs/adr tree, not fixtures, which covers regression tests for specific citation/drift bugs instead.

**Why:** keeps drift-logic tests independent of the real ADR's prose, so future edits to `docs/adr/0052-sandbox-tier-scenarios.md` don't silently break drift-suppression coverage.
