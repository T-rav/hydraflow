---
id: 0127
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:45:43.966326+00:00
status: superseded
corroborations: 1
supersedes: 0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091
superseded_by: 0134
---

# Memory eviction must atomically update scores and items files

An eviction operation must write `item_scores.json` and `items.jsonl` together within the same lock scope — never update one without the other.

Example: `atomic_write(scores_path, ...)` then `atomic_write(items_path, ...)` under a single lock acquire.

**Why:** A partial update leaves scores referencing evicted items (or items with stale scores), corrupting ranking on the next eviction pass.
