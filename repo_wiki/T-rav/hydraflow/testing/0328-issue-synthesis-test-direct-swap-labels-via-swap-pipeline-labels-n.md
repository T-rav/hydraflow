---
id: 0328
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:56:41.024112+00:00
status: superseded
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
superseded_by: 0334
---

# Test direct-swap labels via swap_pipeline_labels(), not transitions

Labels set via atomic swap (`hitl-active`, `fixed`) bypass the transition graph and are applied by `swap_pipeline_labels()` — test them on that call path.

Example: Do not test swap labels through `VALID_TRANSITIONS`. See also: testing — Sync test label constants with production pipeline definitions.

**Why:** Testing swap labels through the transition graph masks missing coverage; they have no transition entry by design.
