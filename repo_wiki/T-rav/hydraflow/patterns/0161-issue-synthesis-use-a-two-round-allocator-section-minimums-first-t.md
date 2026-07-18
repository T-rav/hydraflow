---
id: 0161
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:34:46.627737+00:00
status: active
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
---

# Use a two-round allocator: section minimums first, then proportional surplus

Round one gives each memory section its minimum budget; round two distributes the remainder proportionally by `_DEFAULT_PRIORITIES` label.

Example: `min_alloc = {k: MINIMUMS[k] for k in sections}; surplus = total - sum(min_alloc.values()); prop += surplus * weights`.

**Why:** A single-round proportional allocator can starve low-priority sections below their functional minimum, breaking prompt structure.
