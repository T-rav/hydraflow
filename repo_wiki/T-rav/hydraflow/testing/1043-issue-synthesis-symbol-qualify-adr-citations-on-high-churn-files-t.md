---
id: 1043
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.497117+00:00
status: superseded
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
superseded_by: 1085
---

# Symbol-qualify ADR citations on high-churn files to stop false drift

When an ADR cites a file that changes on every unrelated PR (e.g. src/mockworld/sandbox_main.py), narrow the citation to a symbol suffix like :main instead of a bare file path.

Example: src/adr_drift.py (#9176) only diffs at file granularity — a bare file citation flags drift on any touch, while a symbol-qualified one only flags drift when that specific symbol shows up in evidence. Used in ADR-0052 to stop routine per-loop seam additions from tripping the drift auditor. See also: ADR citations must stay bare when fixing drift (that rule governs widening scope during a content fix; this one is deliberate narrowing on noisy registry files).

**Why:** prevents recurring false-positive drift rollups on ADRs that cite registry-style files touched by every new-loop PR.
