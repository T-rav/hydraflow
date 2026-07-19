---
id: 0202
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:22:06.637077+00:00
status: active
corroborations: 1
supersedes: 0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175
---

# Pre-allocate memory budget upfront before prompt assembly

Call `get_allocation()` and consume all budget caps before starting `_inject_memory()` — post-hoc surplus reclamation is not possible.

Example: allocate wiki budget first, deduct from surplus, then distribute remaining memory budget proportionally.

**Why:** Prompt assembly is streaming; once a section is written, its token budget cannot be reclaimed for a different section.
