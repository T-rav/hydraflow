---
id: 0445
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:46:15.867022+00:00
status: superseded
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401,0402,0403,0404,0405,0406,0407,0408,0409,0410,0411
superseded_by: 0451
---

# Test direct-swap labels via swap_pipeline_labels()

Labels set via atomic swap (`hitl-active`, `fixed`) bypass the transition graph and are applied by `swap_pipeline_labels()` — test them on that call path.

Example: Do not test swap labels through `VALID_TRANSITIONS`. See also: testing — Sync test label constants with production definitions.

**Why:** Testing swap labels through the transition graph masks missing coverage; they have no transition entry by design.
