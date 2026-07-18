---
id: 0076
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T14:57:29.438732+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
---

# Pre-allocate memory budget upfront before prompt assembly

Call `get_allocation()` and consume all budget caps before starting `_inject_memory()` — post-hoc surplus reclamation is not possible.

Example: allocate wiki budget first, deduct from surplus, then distribute remaining memory budget proportionally. See also: patterns — Use a two-round allocator for memory sections.

**Why:** Prompt assembly is streaming; once a section is written, its token budget cannot be reclaimed for a different section.
