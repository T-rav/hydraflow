---
id: 0133
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:37:07.468790+00:00
status: active
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
---

# Use same ID extraction logic everywhere files are keyed by issue

Define ID prefix lengths as named constants and centralize extraction so every site that keys files by issue uses identical logic.

Example: define `DISCOVER_PREFIX_LEN = 9`; use it in both the writer and the reader rather than hardcoding `fname[9:]` in each.

**Why:** Inconsistent ID logic causes silent lookup failures — a plan is written under key A but read back under key B, producing phantom missing plans.
