---
id: 1045
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.503015+00:00
status: superseded
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
superseded_by: 1085
---

# Test drift-suppression logic with synthetic ADR fixtures in unit tests

In tests/test_adr_drift.py, prove new citation-drift behavior (e.g. symbol-qualified citations suppressing drift on file-only touches) by driving compute_drift/_citation_drifts with a synthetic ADR object carrying the new citation form, plus a bare-citation case as a regression guard for existing behavior.

Example: pair with tests/test_adr_index.py assertions that parse_adr_file correctly parses the citation into source_symbols/source_files. See also: ADR-drift regressions replay real merged PR files through production ADRIndex, not fixtures, which covers regression tests for specific citation/drift bugs instead.

**Why:** keeps drift-logic tests independent of the real ADR's prose, so future edits to docs/adr/0052-sandbox-tier-scenarios.md don't silently break drift-suppression coverage.
