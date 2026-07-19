---
id: 0249
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:45:28.228898+00:00
status: active
corroborations: 1
supersedes: 0176,0177,0178,0179,0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216,0217
---

# Use asymmetric word-set overlap for memory deduplication

Compute dedup similarity as `len(words & existing) / max(len(words), 1)` with a configurable threshold (default 0.85).

Example: New item with 10 words sharing 9 with an existing item → score 0.9 → suppress.

**Why:** Symmetric Jaccard penalises short additions to long entries; asymmetric overlap correctly identifies content that's mostly a subset of existing memory.
