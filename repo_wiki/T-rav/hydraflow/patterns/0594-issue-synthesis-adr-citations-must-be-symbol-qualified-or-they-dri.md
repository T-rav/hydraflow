---
id: 0594
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.337991+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# ADR citations must be symbol-qualified or they drift-flag every file touch

Qualify ADR code citations as `path:Symbol`, not a bare file path, or they drift-flag every unrelated touch to that file.

Example: in `src/adr_drift.py`, a bare `src/epic.py` citation triggers `_citation_drifts` on any diff; use `src/epic.py:EpicManager.release_epic` instead. See also: patterns — docs/arch/generated/* is a make arch-regen artifact.

**Why:** prevents false-positive drift rollups on orthogonal changes to a shared file.
