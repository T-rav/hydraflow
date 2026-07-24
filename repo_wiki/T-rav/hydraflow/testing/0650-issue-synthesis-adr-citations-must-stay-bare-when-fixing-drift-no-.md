---
id: 0650
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:31:08.496739+00:00
status: active
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631
---

# ADR citations must stay bare when fixing drift — no `:Symbol` tail

When amending an ADR to fix drift, do not upgrade a bare `src/triage_phase.py` citation to a `:Symbol`-qualified one and do not add new `src/...py` citations, even if the fix references a specific function like `triage_infra_parked`. `parse_adr_file`'s `source_files` set for the ADR must stay unchanged after the edit. See also: testing — Symbol-qualify ADR citations on high-churn files to stop false drift (a distinct, proactive narrowing used on noisy registry files — not the same as widening scope mid-fix).

**Why:** widening citation scope beyond the drifted claim pulls unrelated code under that ADR's authority and breaks the narrow-scope contract regression tests check for (see `tests/regressions/test_issue_10304.py`).
