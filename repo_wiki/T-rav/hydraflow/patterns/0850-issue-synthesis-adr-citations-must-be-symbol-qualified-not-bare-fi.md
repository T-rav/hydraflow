---
id: 0850
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T19:37:32.618063+00:00
status: active
corroborations: 1
supersedes: 0795
---

# ADR citations must be symbol-qualified, not bare file paths

Qualify ADR code citations as `path:Symbol`, not a bare file path, or they drift-flag every unrelated touch to that file.

Example: In `src/adr_drift.py:65-83`, a bare `src/epic.py` citation triggers `_citation_drifts` on any diff; use `src/epic.py:EpicManager.release_epic` so `compute_drift` only flags diffs touching those symbols, as ADR-0011, ADR-0080, and ADR-0081 already do. See also: patterns — docs/arch/generated/* is a make arch-regen artifact.

**Why:** Prevents false-positive drift rollups (like #10384) on orthogonal changes to a shared file.
