---
id: 0169
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:52:49.031353+00:00
status: active
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
---

# Memory eviction must atomically update scores and items files

An eviction operation must write `item_scores.json` and `items.jsonl` together within the same lock scope — never update one without the other.

Example: `atomic_write(scores_path, ...)` then `atomic_write(items_path, ...)` under a single lock acquire.

**Why:** A partial update leaves scores referencing evicted items (or items with stale scores), corrupting ranking on the next eviction pass.
