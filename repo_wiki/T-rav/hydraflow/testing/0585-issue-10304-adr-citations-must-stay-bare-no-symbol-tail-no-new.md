---
id: 0585
topic: testing
source_issue: 10304
source_phase: plan
created_at: 2026-07-24T03:55:27.919578+00:00
status: superseded
corroborations: 1
superseded_by: 0593
---

# ADR citations must stay bare — no `:Symbol` tail, no new source_files entries

When amending an ADR to fix drift, do not upgrade a bare `src/triage_phase.py` citation to a `:Symbol`-qualified one and do not add new `src/...py` citations, even if the fix references a specific function like `triage_infra_parked`. `parse_adr_file`'s `source_files` set for the ADR must stay unchanged after the edit.

**Why:** widening citation scope beyond the drifted claim pulls unrelated code under that ADR's authority and breaks the narrow-scope contract regression tests check for (see `tests/regressions/test_issue_10304.py`).
