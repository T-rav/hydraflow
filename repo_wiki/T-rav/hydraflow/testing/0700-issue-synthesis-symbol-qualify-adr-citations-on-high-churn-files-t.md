---
id: 0700
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.875715+00:00
status: superseded
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
superseded_by: 0712
---

# Symbol-qualify ADR citations on high-churn files to stop false drift

When an ADR cites a file that changes on every unrelated PR (e.g. `src/mockworld/sandbox_main.py`), narrow the citation to a symbol suffix like `:main` instead of a bare file path.

Example: `src/adr_drift.py` (#9176) only diffs at file granularity — a bare file citation flags drift on any touch, while a symbol-qualified one only flags drift when that specific symbol shows up in evidence. Used in ADR-0052 to stop routine per-loop seam additions from tripping the drift auditor. See also: testing — ADR citations must stay bare when fixing drift (that rule governs widening scope during a content fix; this one is deliberate narrowing on noisy registry files).

**Why:** prevents recurring false-positive drift rollups on ADRs that cite registry-style files touched by every new-loop PR.
