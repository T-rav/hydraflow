---
id: 0118
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:45:43.964089+00:00
status: active
corroborations: 1
supersedes: 0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091
---

# Pre-allocate memory budget upfront before prompt assembly

Call `get_allocation()` and consume all budget caps before starting `_inject_memory()` — post-hoc surplus reclamation is not possible.

Example: allocate wiki budget first, deduct from surplus, then distribute remaining memory budget proportionally.

**Why:** Prompt assembly is streaming; once a section is written, its token budget cannot be reclaimed for a different section.
