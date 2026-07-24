---
id: 0443
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:06:34.706105+00:00
status: superseded
corroborations: 1
supersedes: 0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431
superseded_by: 0447
---

# ADR citations must be symbol-qualified or they drift-flag every file touch

Qualify ADR code citations as `path:Symbol`, not a bare file path, or they drift-flag every unrelated touch to that file. Example: in `src/adr_drift.py:65-83`, a bare `src/epic.py` citation is read as file-granular, so any diff — even a read-only display change — triggers `_citation_drifts`; use `src/epic.py:EpicManager.release_epic` instead so `source_symbols["src/epic.py"]` is populated and `compute_drift` only flags diffs touching those symbols, as ADR-0011, ADR-0080, and ADR-0081 already do. **Why:** prevents false-positive drift rollups (like #10384) on orthogonal changes to a shared file.
