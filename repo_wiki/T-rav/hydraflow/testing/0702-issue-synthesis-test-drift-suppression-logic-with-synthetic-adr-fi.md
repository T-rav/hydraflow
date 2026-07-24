---
id: 0702
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.878305+00:00
status: superseded
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
superseded_by: 0712
---

# Test drift-suppression logic with synthetic ADR fixtures in unit tests

In `tests/test_adr_drift.py`, prove new citation-drift behavior (e.g. symbol-qualified citations suppressing drift on file-only touches) by driving `compute_drift`/`_citation_drifts` with a synthetic ADR object carrying the new citation form, plus a bare-citation case as a regression guard for existing behavior.

Example: pair with `tests/test_adr_index.py` assertions that `parse_adr_file` correctly parses the citation into `source_symbols`/`source_files`. This applies to unit tests of the drift *mechanism* itself — see also: testing — ADR drift regressions must drive the real docs/adr tree, not fixtures, which covers regression tests for specific citation/drift bugs instead.

**Why:** keeps drift-logic tests independent of the real ADR's prose, so future edits to `docs/adr/0052-sandbox-tier-scenarios.md` don't silently break drift-suppression coverage.
