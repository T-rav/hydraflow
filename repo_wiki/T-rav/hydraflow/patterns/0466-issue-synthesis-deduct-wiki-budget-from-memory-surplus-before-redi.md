---
id: 0466
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T15:40:09.604826+00:00
status: active
corroborations: 1
supersedes: 0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462
---

# Deduct wiki budget from memory surplus before redistributing

Compute the wiki budget (`max_repo_wiki_chars`) and subtract it from the memory surplus before distributing the remainder proportionally across memory sections.

Example: `surplus -= wiki_budget; memory_alloc = distribute(surplus, weights)`.

**Why:** not deducting first causes memory sections to over-allocate, then the wiki gets truncated when both compete for the same token pool.
