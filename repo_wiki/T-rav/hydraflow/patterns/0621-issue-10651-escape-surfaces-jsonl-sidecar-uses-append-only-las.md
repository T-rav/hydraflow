---
id: 0621
topic: patterns
source_issue: 10651
source_phase: plan
created_at: 2026-07-26T15:47:34.663659+00:00
status: active
corroborations: 1
---

# escape_surfaces.jsonl sidecar uses append-only, last-row-wins per fingerprint

Treat `escape_surfaces.jsonl` as append-only; the terminal state for any fingerprint is the last row written for it. When adding new lifecycle fields (e.g. `attempts`, `abandoned_at`), append new rows rather than mutating old ones.

- `src/escape/surfaces.py`: `attempts_by_fingerprint()` reads the sidecar and takes the count from the last row per fingerprint.
- `open_links()` reconstructs current state by replaying to the last row per fingerprint.

**Why:** Mutation of historical rows would break readers that rely on replay semantics and would corrupt the audit trail used by reconcile and UI.
