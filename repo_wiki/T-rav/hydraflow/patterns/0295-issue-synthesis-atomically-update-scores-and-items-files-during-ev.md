---
id: 0295
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:42:57.722050+00:00
status: superseded
corroborations: 1
supersedes: 0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255,0256,0257,0258,0259
superseded_by: 0302
---

# Atomically update scores and items files during eviction

An eviction operation must write `item_scores.json` and `items.jsonl` together within the same lock scope — never update one without the other.

Example: `atomic_write(scores_path, ...)` then `atomic_write(items_path, ...)` under a single lock acquire.

**Why:** A partial update leaves scores referencing evicted items (or items with stale scores), corrupting ranking on the next eviction pass.
