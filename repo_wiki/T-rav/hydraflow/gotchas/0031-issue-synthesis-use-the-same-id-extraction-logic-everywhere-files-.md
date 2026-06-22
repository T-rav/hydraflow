---
id: 0031
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.696488+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Use the same ID extraction logic everywhere files are keyed by issue

Define ID prefix lengths as named constants and centralize extraction so every site that keys files by issue uses identical logic.

Example: define `DISCOVER_PREFIX_LEN = 9`; use it in both the writer and the reader rather than hardcoding `fname[9:]` in each.

**Why:** Inconsistent ID logic causes silent lookup failures — a plan is written under key A but read back under key B, producing phantom missing plans.
