---
id: 0063
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:16:33.337696+00:00
status: active
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
---

# New HydraFlowConfig label fields must be optional in ConfigFactory

When adding a `list[str]` label field to `HydraFlowConfig`, add it as an optional `ConfigFactory.create()` parameter with a sensible default.

Example: omitting the parameter causes `TypeError: create() got an unexpected keyword argument` in every test fixture that constructs a config.

**Why:** `ConfigFactory.create()` is called across the entire test suite; missing parameters break all tests that construct a config without the new field.
