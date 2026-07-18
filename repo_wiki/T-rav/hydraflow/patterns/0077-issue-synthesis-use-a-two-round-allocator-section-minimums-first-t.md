---
id: 0077
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:15:44.534657+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
---

# Use a two-round allocator: section minimums first, then proportional surplus

Round one gives each memory section its minimum budget; round two distributes the remainder proportionally by `_DEFAULT_PRIORITIES` label.

Example: `min_alloc = {k: MINIMUMS[k] for k in sections}; surplus = total - sum(min_alloc.values()); prop += surplus * weights`.

**Why:** A single-round proportional allocator can starve low-priority sections below their functional minimum, breaking prompt structure.
