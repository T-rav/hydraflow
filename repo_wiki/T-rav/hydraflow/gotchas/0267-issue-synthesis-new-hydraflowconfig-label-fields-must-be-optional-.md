---
id: 0267
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:39:19.029076+00:00
status: active
corroborations: 1
supersedes: 0214,0215,0216,0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247
---

# New HydraFlowConfig label fields must be optional in ConfigFactory

When adding a `list[str]` label field to `HydraFlowConfig`, add it as an optional `ConfigFactory.create()` parameter with a sensible default.

Example: omitting the parameter causes `TypeError: create() got an unexpected keyword argument` in every test fixture that constructs a config.

**Why:** `ConfigFactory.create()` is called across the entire test suite; missing parameters break all tests that construct a config without the new field.
