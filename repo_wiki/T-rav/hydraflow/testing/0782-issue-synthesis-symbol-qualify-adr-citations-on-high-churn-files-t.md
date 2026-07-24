---
id: 0782
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:12:20.342145+00:00
status: superseded
corroborations: 1
supersedes: 0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753
superseded_by: 0798
---

# Symbol-qualify ADR citations on high-churn files to stop false drift

When an ADR cites a file that changes on every unrelated PR (e.g. `src/mockworld/sandbox_main.py`), narrow the citation to a symbol suffix like `:main` instead of a bare file path.

Example: `src/adr_drift.py` (#9176) only diffs at file granularity — a bare file citation flags drift on any touch, while a symbol-qualified one only flags drift when that specific symbol shows up in evidence. Used in ADR-0052 to stop routine per-loop seam additions from tripping the drift auditor. See also: ADR citations must stay bare when fixing drift (that rule governs widening scope during a content fix; this one is deliberate narrowing on noisy registry files).

**Why:** prevents recurring false-positive drift rollups on ADRs that cite registry-style files touched by every new-loop PR.
