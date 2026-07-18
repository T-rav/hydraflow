---
id: 0099
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:46:56.519500+00:00
status: active
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
---

# Use same ID extraction logic everywhere files are keyed by issue

Define ID prefix lengths as named constants and centralize extraction so every site that keys files by issue uses identical logic.

Example: define `DISCOVER_PREFIX_LEN = 9`; use it in both the writer and the reader rather than hardcoding `fname[9:]` in each.

**Why:** Inconsistent ID logic causes silent lookup failures — a plan is written under key A but read back under key B, producing phantom missing plans.
