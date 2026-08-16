---
id: 3065
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T04:41:05.197080+00:00
status: superseded
corroborations: 1
supersedes: 2931
superseded_by: 3198
---

# Deduct wiki budget from memory surplus before redistributing

Compute the wiki budget (`max_repo_wiki_chars`) and subtract it from the memory surplus before distributing the remainder proportionally across memory sections.

Example: `surplus -= wiki_budget; memory_alloc = distribute(surplus, weights)`.

**Why:** Not deducting first causes memory sections to over-allocate, then the wiki gets truncated when both compete for the same token pool.
