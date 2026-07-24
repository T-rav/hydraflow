---
id: 0621
topic: testing
source_issue: 10386
source_phase: plan
created_at: 2026-07-24T04:38:03.777818+00:00
status: superseded
corroborations: 1
superseded_by: 0632
---

# Symbol-qualify ADR citations on high-churn files to stop false drift

When an ADR cites a file that changes on every unrelated PR (e.g. `src/mockworld/sandbox_main.py`), narrow the citation to a symbol suffix like `:main` instead of a bare file path. `src/adr_drift.py` (#9176) only diffs at file granularity — a bare file citation flags drift on any touch, while a symbol-qualified one only flags drift when that specific symbol shows up in evidence. Used in ADR-0052 to stop routine per-loop seam additions from tripping the drift auditor.

**Why:** prevents recurring false-positive drift rollups on ADRs that cite registry-style files touched by every new-loop PR.
