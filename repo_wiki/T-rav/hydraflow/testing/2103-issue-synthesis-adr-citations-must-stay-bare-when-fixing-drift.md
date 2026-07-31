---
id: 2103
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.210422+00:00
status: active
corroborations: 1
supersedes: 1973
---

# ADR citations must stay bare when fixing drift

When amending an ADR to fix drift, do not upgrade a bare src/triage_phase.py citation to a :Symbol-qualified one and do not add new src/...py citations, even if the fix references a specific function.

Example: parse_adr_file's source_files set for the ADR must stay unchanged after the edit. See also: testing — ADR source-file citations must be :Symbol-qualified.

**Why:** Widening citation scope beyond the drifted claim pulls unrelated code under that ADR's authority and breaks narrow-scope regression tests (tests/regressions/test_issue_10304.py).
