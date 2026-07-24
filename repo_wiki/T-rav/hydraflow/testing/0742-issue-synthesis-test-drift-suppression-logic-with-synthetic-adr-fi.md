---
id: 0742
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.335438+00:00
status: superseded
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
superseded_by: 0754
---

# Test drift-suppression logic with synthetic ADR fixtures in unit tests

In `tests/test_adr_drift.py`, prove new citation-drift behavior (e.g. symbol-qualified citations suppressing drift on file-only touches) by driving `compute_drift`/`_citation_drifts` with a synthetic ADR object carrying the new citation form, plus a bare-citation case as a regression guard for existing behavior.

Example: pair with `tests/test_adr_index.py` assertions that `parse_adr_file` correctly parses the citation into `source_symbols`/`source_files`. This applies to unit tests of the drift *mechanism* itself — see also: testing — ADR drift regressions must drive the real docs/adr tree, not fixtures, which covers regression tests for specific citation/drift bugs instead.

**Why:** keeps drift-logic tests independent of the real ADR's prose, so future edits to `docs/adr/0052-sandbox-tier-scenarios.md` don't silently break drift-suppression coverage.
