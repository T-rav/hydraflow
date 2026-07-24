---
id: 0623
topic: testing
source_issue: 10386
source_phase: plan
created_at: 2026-07-24T04:38:03.777859+00:00
status: superseded
corroborations: 1
superseded_by: 0632
---

# Test drift-suppression behavior with synthetic ADR fixtures, not the real ADR

In `tests/test_adr_drift.py`, prove new citation-drift behavior (e.g. symbol-qualified citations suppressing drift on file-only touches) by driving `compute_drift`/`_citation_drifts` with a synthetic ADR object carrying the new citation form, plus a bare-citation case as a regression guard for existing behavior. Pair with `tests/test_adr_index.py` assertions that `parse_adr_file` correctly parses the citation into `source_symbols`/`source_files`.

**Why:** keeps drift-logic tests independent of the real ADR's prose, so future edits to `docs/adr/0052-sandbox-tier-scenarios.md` don't silently break drift-suppression coverage.
