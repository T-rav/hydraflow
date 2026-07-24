---
id: 0399
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:23:13.611802+00:00
status: active
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387
---

# ADR citations must be symbol-qualified or they drift-flag every file touch

In `src/adr_drift.py:65-83`, a bare `src/epic.py` citation (path in its own backticks) is read as file-granular, so ANY diff to that file — even a read-only display change — triggers `_citation_drifts` and fires a rollup.

Example: qualify citations as `src/epic.py:EpicManager.release_epic` so `source_symbols["src/epic.py"]` is populated and `compute_drift` only flags diffs touching those specific symbols; ADR-0011, ADR-0080, and ADR-0081 already use this `path:Symbol` form.

**Why:** prevents false-positive drift rollups (like #10384) on orthogonal changes to a shared file.
