---
id: 0406
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:49:52.751806+00:00
status: superseded
corroborations: 1
supersedes: 0334,0335,0336,0337,0338,0339,0340,0341,0342,0343,0344,0345,0346,0347,0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369,0370,0371,0372
superseded_by: 0412
---

# Test direct-swap labels via swap_pipeline_labels()

Labels set via atomic swap (`hitl-active`, `fixed`) bypass the transition graph and are applied by `swap_pipeline_labels()` — test them on that call path.

Example: Do not test swap labels through `VALID_TRANSITIONS`. See also: testing — Sync test label constants with production definitions.

**Why:** Testing swap labels through the transition graph masks missing coverage; they have no transition entry by design.
