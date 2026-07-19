---
id: 0081
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:15:44.536516+00:00
status: superseded
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
superseded_by: 0092
---

# Use asymmetric word-set overlap for memory deduplication

Compute dedup similarity as `len(words & existing) / max(len(words), 1)` with a configurable threshold (default 0.85).

Example: new item with 10 words sharing 9 with an existing item → score 0.9 → suppress.

**Why:** Symmetric Jaccard penalises short additions to long entries; asymmetric overlap correctly identifies content that's mostly a subset of existing memory.
