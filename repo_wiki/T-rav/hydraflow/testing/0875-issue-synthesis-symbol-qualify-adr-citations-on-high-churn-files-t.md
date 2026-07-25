---
id: 0875
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:22:24.460469+00:00
status: superseded
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
superseded_by: 0897
---

# Symbol-qualify ADR citations on high-churn files to stop false drift

When an ADR cites a file that changes on every unrelated PR (e.g. `src/mockworld/sandbox_main.py`), narrow the citation to a symbol suffix like `:main` instead of a bare file path.

Example: `src/adr_drift.py` (#9176) only diffs at file granularity — a bare file citation flags drift on any touch, while a symbol-qualified one only flags drift when that specific symbol shows up in evidence. Used in ADR-0052 to stop routine per-loop seam additions from tripping the drift auditor. See also: ADR citations must stay bare when fixing drift (that rule governs widening scope during a content fix; this one is deliberate narrowing on noisy registry files).

**Why:** prevents recurring false-positive drift rollups on ADRs that cite registry-style files touched by every new-loop PR.
