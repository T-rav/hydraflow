---
id: 0123
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T05:57:54.431701+00:00
status: superseded
corroborations: 1
supersedes: 0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122
superseded_by: 0153
---

# Mock at definition site, not at the import site

Patch symbols at the module where they are defined, not where they are imported.

- Bad: `patch('tests.test_foo.MyClass')`
- Good: `patch('src.mymodule.MyClass')`

For optional deps like `sentry_sdk`, use `patch.dict('sys.modules', {'sentry_sdk': mock, 'sentry_sdk.integrations': mock})`; patch sub-modules explicitly to prevent import leaks.

**Why:** Usage-site patches intercept only that one import; other callers and subsequent imports still see the real object, producing inconsistent test behavior.
