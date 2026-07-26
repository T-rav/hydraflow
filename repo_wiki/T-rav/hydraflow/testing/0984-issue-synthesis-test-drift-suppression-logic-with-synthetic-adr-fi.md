---
id: 0984
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.576593+00:00
status: superseded
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
superseded_by: 1015
---

# Test drift-suppression logic with synthetic ADR fixtures in unit tests

In tests/test_adr_drift.py, prove new citation-drift behavior (e.g. symbol-qualified citations suppressing drift on file-only touches) by driving compute_drift/_citation_drifts with a synthetic ADR object carrying the new citation form, plus a bare-citation case as a regression guard for existing behavior.

Example: pair with tests/test_adr_index.py assertions that parse_adr_file correctly parses the citation into source_symbols/source_files. This applies to unit tests of the drift mechanism itself — see also: ADR drift regressions must drive the real docs/adr tree, not fixtures, which covers regression tests for specific citation/drift bugs instead.

**Why:** keeps drift-logic tests independent of the real ADR's prose, so future edits to docs/adr/0052-sandbox-tier-scenarios.md don't silently break drift-suppression coverage.
