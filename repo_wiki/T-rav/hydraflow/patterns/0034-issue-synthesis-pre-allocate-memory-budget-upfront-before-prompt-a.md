---
id: 0034
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.318127+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Pre-allocate memory budget upfront before prompt assembly

Call `get_allocation()` and consume all budget caps before starting `_inject_memory()` — post-hoc surplus reclamation is not possible.

Example: allocate wiki budget first, deduct from surplus, then distribute remaining memory budget proportionally.

**Why:** Prompt assembly is streaming; once a section is written, its token budget cannot be reclaimed for a different section.
