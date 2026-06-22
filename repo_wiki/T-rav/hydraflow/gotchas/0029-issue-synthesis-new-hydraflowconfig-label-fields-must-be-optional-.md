---
id: 0029
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.696116+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# New HydraFlowConfig label fields must be optional params in ConfigFactory

When adding a `list[str]` label field to `HydraFlowConfig`, add it as an optional `ConfigFactory.create()` parameter with a sensible default.

Example: omitting the parameter causes `TypeError: create() got an unexpected keyword argument` in every test fixture that constructs a config.

**Why:** `ConfigFactory.create()` is called across the entire test suite; missing parameters break all tests that construct a config without the new field.
