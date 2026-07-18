---
id: 0292
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:48:26.502909+00:00
status: active
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
---

# Assert numeric values in Sentry breadcrumbs, not just key presence

When testing Sentry integration, assert actual numeric values in breadcrumbs and metrics, not just that a key exists.

```python
# good
assert breadcrumb['data']['latency_ms'] == 42
```

**Why:** Key-presence assertions pass even when values are wrong or zero; numeric value assertions catch metric miscalculation bugs that presence checks miss entirely.
