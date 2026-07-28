---
id: 0721
topic: patterns
source_issue: 10753
source_phase: plan
created_at: 2026-07-27T23:48:50.234442+00:00
status: active
corroborations: 1
---

# WikiCompiler forced fold folds unclaimed entries onto unrelated primaries

In `WikiCompiler._resolve_supersession_ids`, the `or primary_id` fallback forces unclaimed entries onto an unrelated primary. Drop this fallback so unclaimed entries stay `active` with no `superseded_by`.

Example: a synthesis round with an unclaimed entry should leave it `active`, not fold it onto the primary.

**Why:** The forced fold is the write-path root cause of orphan-fold defects like #10750; without removing it, restored entries get re-folded on the next `RepoWikiLoop` tick.
