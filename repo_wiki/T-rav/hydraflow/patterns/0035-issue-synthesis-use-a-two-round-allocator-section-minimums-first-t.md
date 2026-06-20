---
id: 0035
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.318328+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Use a two-round allocator: section minimums first, then proportional surplus

Round one gives each memory section its minimum budget; round two distributes the remainder proportionally by `_DEFAULT_PRIORITIES` label.

Example: `min_alloc = {k: MINIMUMS[k] for k in sections}; surplus = total - sum(min_alloc.values()); prop += surplus * weights`.

**Why:** A single-round proportional allocator can starve low-priority sections below their functional minimum, breaking prompt structure.
