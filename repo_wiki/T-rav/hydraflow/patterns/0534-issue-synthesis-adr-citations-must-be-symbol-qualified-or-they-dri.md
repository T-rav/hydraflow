---
id: 0534
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:44:03.240058+00:00
status: superseded
corroborations: 1
supersedes: 0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522
superseded_by: 0550
---

# ADR citations must be symbol-qualified or they drift-flag every file touch

Qualify ADR code citations as `path:Symbol`, not a bare file path, or they drift-flag every unrelated touch to that file.

Example: in `src/adr_drift.py:65-83`, a bare `src/epic.py` citation is read as file-granular, so any diff — even a read-only display change — triggers `_citation_drifts`; use `src/epic.py:EpicManager.release_epic` instead so `source_symbols["src/epic.py"]` is populated and `compute_drift` only flags diffs touching those symbols, as ADR-0011, ADR-0080, and ADR-0081 already do. See also: patterns — arch-regen normalizes away :Symbol citation suffixes.

**Why:** prevents false-positive drift rollups (like #10384) on orthogonal changes to a shared file.
