---
id: 0561
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:39:17.747465+00:00
status: superseded
corroborations: 1
supersedes: 0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0542,0543,0544,0545,0546,0547,0548,0549
superseded_by: 0584
---

# ADR citations must be symbol-qualified or they drift-flag every file touch

Qualify ADR code citations as `path:Symbol`, not a bare file path, or they drift-flag every unrelated touch to that file.

Example: in `src/adr_drift.py:65-83`, a bare `src/epic.py` citation is read as file-granular, so any diff — even a read-only display change — triggers `_citation_drifts`; use `src/epic.py:EpicManager.release_epic` instead so `source_symbols["src/epic.py"]` is populated and `compute_drift` only flags diffs touching those symbols, as ADR-0011, ADR-0080, and ADR-0081 already do. See also: patterns — docs/arch/generated/* is a make arch-regen artifact.

**Why:** prevents false-positive drift rollups (like #10384) on orthogonal changes to a shared file.
