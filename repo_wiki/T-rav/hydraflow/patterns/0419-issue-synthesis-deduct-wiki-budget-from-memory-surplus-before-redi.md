---
id: 0419
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:37:01.321841+00:00
status: active
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415
---

# Deduct wiki budget from memory surplus before redistributing

Compute the wiki budget (`max_repo_wiki_chars`) and subtract it from the memory surplus before distributing the remainder proportionally across memory sections. Example: `surplus -= wiki_budget; memory_alloc = distribute(surplus, weights)`. **Why:** not deducting first causes memory sections to over-allocate, then the wiki gets truncated when both compete for the same token pool.
