---
id: 0039
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.319206+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Use asymmetric word-set overlap for memory deduplication

Compute dedup similarity as `len(words & existing) / max(len(words), 1)` with a configurable threshold (default 0.85).

Example: new item with 10 words sharing 9 with an existing item → score 0.9 → suppress.

**Why:** Symmetric Jaccard penalises short additions to long entries; asymmetric overlap correctly identifies content that's mostly a subset of existing memory.
