---
id: 0123
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:45:43.965282+00:00
status: superseded
corroborations: 1
supersedes: 0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091
superseded_by: 0134
---

# Use asymmetric word-set overlap for memory deduplication

Compute dedup similarity as `len(words & existing) / max(len(words), 1)` with a configurable threshold (default 0.85).

Example: new item with 10 words sharing 9 with an existing item → score 0.9 → suppress.

**Why:** Symmetric Jaccard penalises short additions to long entries; asymmetric overlap correctly identifies content that's mostly a subset of existing memory.
