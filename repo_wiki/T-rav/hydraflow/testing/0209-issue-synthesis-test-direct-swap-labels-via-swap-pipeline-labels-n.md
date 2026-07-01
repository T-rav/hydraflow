---
id: 0209
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.791797+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Test direct-swap labels via swap_pipeline_labels(), not transitions

Labels set via atomic swap (`hitl-active`, `fixed`) bypass the transition graph and are applied by `swap_pipeline_labels()` — test them on that call path, not through `VALID_TRANSITIONS`.

See also: testing — Keep test label/stage constants synchronized with production definitions.

**Why:** Testing swap labels through the transition graph masks missing coverage; they have no transition entry by design.
