---
id: 0093
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.079928+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# Mock at definition site, not at the import site

Patch symbols at the module where they are defined, not where they are imported.

- Bad: `patch('tests.test_foo.MyClass')`
- Good: `patch('src.mymodule.MyClass')`

For optional deps like `sentry_sdk`, use `patch.dict('sys.modules', {'sentry_sdk': mock, 'sentry_sdk.integrations': mock})`; patch sub-modules explicitly to prevent import leaks.

**Why:** Usage-site patches intercept only that one import; other callers and subsequent imports still see the real object, producing inconsistent test behavior.
