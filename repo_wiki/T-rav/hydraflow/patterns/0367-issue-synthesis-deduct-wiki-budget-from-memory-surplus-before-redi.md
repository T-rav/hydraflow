---
id: 0367
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:10:17.163930+00:00
status: superseded
corroborations: 1
supersedes: 0356,0357,0358,0359,0360,0361,0362,0363
superseded_by: 0373
---

# Deduct wiki budget from memory surplus before redistributing

Compute the wiki budget (`max_repo_wiki_chars`) and subtract it from the memory surplus BEFORE distributing the remainder proportionally across memory sections.

Example: `surplus -= wiki_budget; memory_alloc = distribute(surplus, weights)`.

**Why:** Not deducting first causes memory sections to over-allocate, then the wiki gets truncated when both compete for the same token pool.
