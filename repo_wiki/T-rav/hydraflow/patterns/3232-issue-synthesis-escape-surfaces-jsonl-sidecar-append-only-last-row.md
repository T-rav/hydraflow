---
id: 3232
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T06:16:47.030345+00:00
status: active
corroborations: 1
supersedes: 3099
---

# escape_surfaces.jsonl sidecar: append-only, last-row-wins

Treat `escape_surfaces.jsonl` as append-only; the terminal state for any fingerprint is the last row written for it. When adding new lifecycle fields (e.g. `attempts`, `abandoned_at`), append new rows rather than mutating old ones.

Example: `src/escape/surfaces.py`: `attempts_by_fingerprint()` reads the sidecar and takes the count from the last row per fingerprint; `open_links()` reconstructs current state by replaying to the last row.

**Why:** Mutation of historical rows would break readers that rely on replay semantics and would corrupt the audit trail used by reconcile and UI.
