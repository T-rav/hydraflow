---
id: 0435
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:06:34.700464+00:00
status: superseded
corroborations: 1
supersedes: 0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431
superseded_by: 0447
---

# Deduct wiki budget from memory surplus before redistributing

Compute the wiki budget (`max_repo_wiki_chars`) and subtract it from the memory surplus before distributing the remainder proportionally across memory sections. Example: `surplus -= wiki_budget; memory_alloc = distribute(surplus, weights)`. **Why:** not deducting first causes memory sections to over-allocate, then the wiki gets truncated when both compete for the same token pool.
