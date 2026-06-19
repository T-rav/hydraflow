---
id: 0040
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.319423+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Batch-load scoring data once per eviction operation, not per item

Call `MemoryScorer.load_item_scores()` once per eviction pass and reuse the result across all items.

Example: `scores = scorer.load_item_scores(); for item in items: rank(item, scores)`.

**Why:** Per-item score loading reads the same file N times; batch loading makes eviction O(1) in I/O regardless of corpus size.
