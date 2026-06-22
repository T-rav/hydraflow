---
id: 0118
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.086888+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# Test direct-swap labels via swap_pipeline_labels(), not transitions

Labels set via atomic swap (`hitl-active`, `fixed`) bypass the transition graph and are applied by `swap_pipeline_labels()` — test them on that separate call path, not through `VALID_TRANSITIONS`.

See also: testing — Keep test label/stage constants synchronized with production definitions.

**Why:** Testing swap labels through the transition graph masks missing coverage; they have no transition entry by design.
