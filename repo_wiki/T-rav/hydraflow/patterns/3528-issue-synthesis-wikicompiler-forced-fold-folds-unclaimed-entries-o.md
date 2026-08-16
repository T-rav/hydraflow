---
id: 3528
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T12:13:22.334258+00:00
status: superseded
corroborations: 1
supersedes: 3381
superseded_by: 3673
---

# WikiCompiler forced fold folds unclaimed entries onto unrelated primaries

In `WikiCompiler._resolve_supersession_ids`, the `or primary_id` fallback forces unclaimed entries onto an unrelated primary. Drop this fallback so unclaimed entries stay `active` with no `superseded_by`.

Example: A synthesis round with an unclaimed entry should leave it `active`, not fold it onto the primary. See also: [patterns] — Orphan restore and write-path fix must ship in same PR; [patterns] — WikiCompiler supersession edges must be per-output.

**Why:** The forced fold is the write-path root cause of orphan-fold defects like #10750; without removing it, restored entries get re-folded on the next `RepoWikiLoop` tick.
