---
id: 0186
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.783966+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Mock at definition site, not at the import site

Patch symbols at the module where they are defined, not where they are imported.

- Bad: `patch('tests.test_foo.MyClass')`
- Good: `patch('src.mymodule.MyClass')`

For optional deps like `sentry_sdk`, use `patch.dict('sys.modules', {'sentry_sdk': mock, 'sentry_sdk.integrations': mock})`; patch sub-modules explicitly to prevent import leaks.

**Why:** Usage-site patches intercept only that one import; other callers and subsequent imports still see the real object, producing inconsistent test behavior.
