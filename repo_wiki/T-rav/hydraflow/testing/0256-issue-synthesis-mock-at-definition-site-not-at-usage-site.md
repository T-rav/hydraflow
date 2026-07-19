---
id: 0256
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:48:26.479306+00:00
status: superseded
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
superseded_by: 0295
---

# Mock at definition site, not at usage site

Patch symbols at the module where they are *defined*, not where they are imported.

- Good: `patch('src.foo._cache')`
- Bad: `patch('src.consumer._cache')`

For optional deps like `sentry_sdk`, use `patch.dict("sys.modules", {"sentry_sdk": mock_sdk, "sentry_sdk.integrations": mock_int})`; patch sub-modules explicitly to prevent import leaks.

**Why:** Usage-site patches intercept only one import; other callers and subsequent imports still see the real object, producing inconsistent test behavior.
