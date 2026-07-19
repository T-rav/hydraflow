---
id: 0165
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:23:52.953224+00:00
status: active
corroborations: 1
supersedes: 0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145
---

# New HydraFlowConfig label fields must be optional in ConfigFactory

When adding a `list[str]` label field to `HydraFlowConfig`, add it as an optional `ConfigFactory.create()` parameter with a sensible default.

Example: omitting the parameter causes `TypeError: create() got an unexpected keyword argument` in every test fixture that constructs a config.

**Why:** `ConfigFactory.create()` is called across the entire test suite; missing parameters break all tests that construct a config without the new field.
