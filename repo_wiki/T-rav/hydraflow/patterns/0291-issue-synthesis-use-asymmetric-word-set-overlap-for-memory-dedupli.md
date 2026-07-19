---
id: 0291
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:42:57.720214+00:00
status: active
corroborations: 1
supersedes: 0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255,0256,0257,0258,0259
---

# Use asymmetric word-set overlap for memory deduplication

Compute dedup similarity as `len(words & existing) / max(len(words), 1)` with a configurable threshold (default 0.85).

Example: New item with 10 words sharing 9 with an existing item → score 0.9 → suppress.

**Why:** Symmetric Jaccard penalises short additions to long entries; asymmetric overlap correctly identifies content that's mostly a subset of existing memory.
