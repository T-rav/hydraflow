---
id: 0082
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:15:44.536959+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
---

# Batch-load scoring data once per eviction operation, not per item

Call `MemoryScorer.load_item_scores()` once per eviction pass and reuse the result across all items.

Example: `scores = scorer.load_item_scores(); for item in items: rank(item, scores)`.

**Why:** Per-item score loading reads the same file N times; batch loading makes eviction O(1) in I/O regardless of corpus size.
