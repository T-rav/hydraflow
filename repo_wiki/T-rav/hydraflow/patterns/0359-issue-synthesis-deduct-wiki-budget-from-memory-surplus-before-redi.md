---
id: 0359
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T18:01:25.883222+00:00
status: active
corroborations: 1
supersedes: 0350,0350,0351,0352,0353,0354,0355
---

# Deduct wiki budget from memory surplus before redistributing

Compute the wiki budget (`max_repo_wiki_chars`) and subtract it from the memory surplus BEFORE distributing the remainder proportionally across memory sections.

Example: `surplus -= wiki_budget; memory_alloc = distribute(surplus, weights)`.

**Why:** Not deducting first causes memory sections to over-allocate, then the wiki gets truncated when both compete for the same token pool.
