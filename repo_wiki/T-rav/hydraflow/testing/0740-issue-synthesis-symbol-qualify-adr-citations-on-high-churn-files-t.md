---
id: 0740
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.333048+00:00
status: active
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
---

# Symbol-qualify ADR citations on high-churn files to stop false drift

When an ADR cites a file that changes on every unrelated PR (e.g. `src/mockworld/sandbox_main.py`), narrow the citation to a symbol suffix like `:main` instead of a bare file path.

Example: `src/adr_drift.py` (#9176) only diffs at file granularity — a bare file citation flags drift on any touch, while a symbol-qualified one only flags drift when that specific symbol shows up in evidence. Used in ADR-0052 to stop routine per-loop seam additions from tripping the drift auditor. See also: testing — ADR citations must stay bare when fixing drift (that rule governs widening scope during a content fix; this one is deliberate narrowing on noisy registry files).

**Why:** prevents recurring false-positive drift rollups on ADRs that cite registry-style files touched by every new-loop PR.
