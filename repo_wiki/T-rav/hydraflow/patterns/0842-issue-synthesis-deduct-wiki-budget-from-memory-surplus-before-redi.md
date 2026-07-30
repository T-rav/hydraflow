---
id: 0842
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T19:37:32.609518+00:00
status: active
corroborations: 1
supersedes: 0787
---

# Deduct wiki budget from memory surplus before redistributing

Compute the wiki budget (`max_repo_wiki_chars`) and subtract it from the memory surplus before distributing the remainder proportionally across memory sections.

Example: `surplus -= wiki_budget; memory_alloc = distribute(surplus, weights)`.

**Why:** Not deducting first causes memory sections to over-allocate, then the wiki gets truncated when both compete for the same token pool.
