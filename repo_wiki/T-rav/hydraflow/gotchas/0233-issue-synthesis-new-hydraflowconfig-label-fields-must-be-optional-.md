---
id: 0233
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:45:05.799618+00:00
status: superseded
corroborations: 1
supersedes: 0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213
superseded_by: 0248
---

# New HydraFlowConfig label fields must be optional in ConfigFactory

When adding a `list[str]` label field to `HydraFlowConfig`, add it as an optional `ConfigFactory.create()` parameter with a sensible default.

Example: omitting the parameter causes `TypeError: create() got an unexpected keyword argument` in every test fixture that constructs a config.

**Why:** `ConfigFactory.create()` is called across the entire test suite; missing parameters break all tests that construct a config without the new field.
