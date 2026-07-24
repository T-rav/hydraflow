---
id: 0405
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:02:15.939791+00:00
status: superseded
corroborations: 1
supersedes: 0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
superseded_by: 0416
---

# Deduct wiki budget from memory surplus before redistributing

Compute the wiki budget (`max_repo_wiki_chars`) and subtract it from the memory surplus before distributing the remainder proportionally across memory sections. Example: `surplus -= wiki_budget; memory_alloc = distribute(surplus, weights)`. **Why:** not deducting first causes memory sections to over-allocate, then the wiki gets truncated when both compete for the same token pool.
