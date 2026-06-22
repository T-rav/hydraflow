---
id: 0214
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.793574+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Assert numeric values in Sentry breadcrumbs, not just key presence

When testing Sentry integration, assert actual numeric values in breadcrumbs and metrics, not just that a key exists.

```python
# good
assert breadcrumb['data']['latency_ms'] == 42
# bad
assert 'latency_ms' in breadcrumb['data']
```

**Why:** Key-presence assertions pass even when values are wrong or zero; numeric value assertions catch metric miscalculation bugs that presence checks miss entirely.
