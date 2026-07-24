---
id: 0927
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T23:41:31.195139+00:00
status: active
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
---

# Test drift-suppression logic with synthetic ADR fixtures in unit tests

In `tests/test_adr_drift.py`, prove new citation-drift behavior (e.g. symbol-qualified citations suppressing drift on file-only touches) by driving `compute_drift`/`_citation_drifts` with a synthetic ADR object carrying the new citation form, plus a bare-citation case as a regression guard for existing behavior.

Example: pair with `tests/test_adr_index.py` assertions that `parse_adr_file` correctly parses the citation into `source_symbols`/`source_files`. This applies to unit tests of the drift *mechanism* itself — see also: ADR drift regressions must drive the real docs/adr tree, not fixtures, which covers regression tests for specific citation/drift bugs instead.

**Why:** keeps drift-logic tests independent of the real ADR's prose, so future edits to `docs/adr/0052-sandbox-tier-scenarios.md` don't silently break drift-suppression coverage.
