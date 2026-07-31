---
id: 1658
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T02:43:14.263057+00:00
status: superseded
corroborations: 1
supersedes: 1575
superseded_by: 1752
---

# Test drift-suppression with synthetic ADR fixtures

In tests/test_adr_drift.py, prove new citation-drift behavior by driving compute_drift/_citation_drifts with a synthetic ADR object carrying the new citation form, plus a bare-citation case as a regression guard.

Example: pair with tests/test_adr_index.py assertions that parse_adr_file correctly parses the citation. See also: testing — ADR-drift regressions replay real PR files through ADRIndex.

**Why:** Keeps drift-logic tests independent of the real ADR's prose, so future edits to docs/adr/ don't silently break drift-suppression coverage.
