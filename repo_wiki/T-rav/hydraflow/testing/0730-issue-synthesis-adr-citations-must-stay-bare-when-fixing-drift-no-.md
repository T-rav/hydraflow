---
id: 0730
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.213447+00:00
status: active
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
---

# ADR citations must stay bare when fixing drift — no `:Symbol` tail

When amending an ADR to fix drift, do not upgrade a bare `src/triage_phase.py` citation to a `:Symbol`-qualified one and do not add new `src/...py` citations, even if the fix references a specific function like `triage_infra_parked`.

Example: `parse_adr_file`'s `source_files` set for the ADR must stay unchanged after the edit. See also: testing — Symbol-qualify ADR citations on high-churn files to stop false drift (a distinct, proactive narrowing used on noisy registry files — not the same as widening scope mid-fix).

**Why:** widening citation scope beyond the drifted claim pulls unrelated code under that ADR's authority and breaks the narrow-scope contract regression tests check for (see `tests/regressions/test_issue_10304.py`).
