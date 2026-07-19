---
id: 0271
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:42:57.711939+00:00
status: active
corroborations: 1
supersedes: 0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255,0256,0257,0258,0259
---

# Mock at the definition site, not the import site

Patch `hindsight.tombstone_safe`, not `module_under_test.tombstone_safe`; combine with deferred imports inside test methods.

Example: `@patch('hindsight.tombstone_safe')` not `@patch('mymodule.tombstone_safe')`.

**Why:** Import-site patches fail when the import is deferred or when optional dependencies are conditionally loaded — definition-site patches intercept regardless of import order.
