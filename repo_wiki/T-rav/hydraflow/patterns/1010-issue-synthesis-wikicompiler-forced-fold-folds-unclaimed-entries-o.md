---
id: 1010
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T04:11:10.552304+00:00
status: superseded
corroborations: 1
supersedes: 0946
superseded_by: 1077
---

# WikiCompiler forced fold folds unclaimed entries onto unrelated primaries

In `WikiCompiler._resolve_supersession_ids`, the `or primary_id` fallback forces unclaimed entries onto an unrelated primary. Drop this fallback so unclaimed entries stay `active` with no `superseded_by`.

Example: A synthesis round with an unclaimed entry should leave it `active`, not fold it onto the primary. See also: patterns — Orphan restore and write-path fix must ship in same PR.

**Why:** The forced fold is the write-path root cause of orphan-fold defects like #10750; without removing it, restored entries get re-folded on the next `RepoWikiLoop` tick.
