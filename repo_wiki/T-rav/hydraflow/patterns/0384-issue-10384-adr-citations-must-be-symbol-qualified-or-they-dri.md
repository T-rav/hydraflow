---
id: 0384
topic: patterns
source_issue: 10384
source_phase: plan
created_at: 2026-07-24T04:55:51.365280+00:00
status: superseded
corroborations: 1
superseded_by: 0388
---

# ADR citations must be symbol-qualified or they drift-flag every file touch

In `src/adr_drift.py:65-83`, a bare `` `src/epic.py` `` citation (path in its own backticks) is read as file-granular, so ANY diff to that file — even a read-only display change — triggers `_citation_drifts` and fires a rollup. Qualify citations as `` `src/epic.py:EpicManager.release_epic` `` so `source_symbols["src/epic.py"]` is populated; then `compute_drift` only flags diffs touching those specific symbols. ADR-0011, ADR-0080, and ADR-0081 already use the correct `path:Symbol` form — match that style when citing owned code from a new ADR.

**Why:** prevents false-positive drift rollups (like #10384) on orthogonal changes to a shared file.
