---
id: 0611
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:57:59.585985+00:00
status: superseded
corroborations: 1
supersedes: 0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0632
---

# ADR citations must stay bare — no `:Symbol` tail, no new source_files entries

When amending an ADR to fix drift, do not upgrade a bare `src/triage_phase.py` citation to a `:Symbol`-qualified one and do not add new `src/...py` citations, even if the fix references a specific function like `triage_infra_parked`. `parse_adr_file`'s `source_files` set for the ADR must stay unchanged after the edit.

**Why:** widening citation scope beyond the drifted claim pulls unrelated code under that ADR's authority and breaks the narrow-scope contract regression tests check for (see `tests/regressions/test_issue_10304.py`).
