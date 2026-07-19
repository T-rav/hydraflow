---
id: 0201
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.157681+00:00
status: active
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
---

# Use same ID extraction logic everywhere files are keyed by issue

Define ID prefix lengths as named constants and centralize extraction so every site that keys files by issue uses identical logic.

Example: define `DISCOVER_PREFIX_LEN = 9`; use it in both the writer and the reader rather than hardcoding `fname[9:]` in each.

**Why:** Inconsistent ID logic causes silent lookup failures — a plan is written under key A but read back under key B, producing phantom missing plans.
