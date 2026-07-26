---
id: 1033
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.469403+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# ADR citations must stay bare when fixing drift — no `:Symbol` tail

When amending an ADR to fix drift, do not upgrade a bare src/triage_phase.py citation to a :Symbol-qualified one and do not add new src/...py citations, even if the fix references a specific function like triage_infra_parked.

Example: parse_adr_file's source_files set for the ADR must stay unchanged after the edit. See also: Symbol-qualify ADR citations on high-churn files to stop false drift (a distinct, proactive narrowing used on noisy registry files, not the same as widening scope mid-fix).

**Why:** widening citation scope beyond the drifted claim pulls unrelated code under that ADR's authority and breaks the narrow-scope contract regression tests check for (see tests/regressions/test_issue_10304.py).
