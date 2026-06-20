---
id: 0043
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.320233+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Memory eviction must atomically update both `item_scores.json` and `items.jsonl`

An eviction operation must write `item_scores.json` and `items.jsonl` together within the same lock scope — never update one without the other.

Example: `atomic_write(scores_path, ...)` then `atomic_write(items_path, ...)` under a single lock acquire.

**Why:** A partial update leaves scores referencing evicted items (or items with stale scores), corrupting ranking on the next eviction pass.
