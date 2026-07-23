---
id: 0178
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.582440+00:00
status: superseded
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
superseded_by: 0183
---

# Test direct-swap labels via swap_pipeline_labels(), not transitions

Labels set via atomic swap (`hitl-active`, `fixed`) bypass the transition graph and are applied by `swap_pipeline_labels()` — test them on that separate call path, not through `VALID_TRANSITIONS`.

See also: testing — Keep test label/stage constants synchronized with production definitions.

**Why:** Testing swap labels through the transition graph masks missing coverage; they have no transition entry by design.
