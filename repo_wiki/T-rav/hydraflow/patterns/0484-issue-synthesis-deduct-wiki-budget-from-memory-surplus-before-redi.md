---
id: 0484
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T22:03:19.141960+00:00
status: active
corroborations: 1
supersedes: 0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480
---

# Deduct wiki budget from memory surplus before redistributing

Compute the wiki budget (`max_repo_wiki_chars`) and subtract it from the memory surplus before distributing the remainder proportionally across memory sections.

Example: `surplus -= wiki_budget; memory_alloc = distribute(surplus, weights)`.

**Why:** not deducting first causes memory sections to over-allocate, then the wiki gets truncated when both compete for the same token pool.
