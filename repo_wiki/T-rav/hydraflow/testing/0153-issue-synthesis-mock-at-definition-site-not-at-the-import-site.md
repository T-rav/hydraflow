---
id: 0153
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.574285+00:00
status: superseded
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
superseded_by: 0183
---

# Mock at definition site, not at the import site

Patch symbols at the module where they are defined, not where they are imported.

- Bad: `patch('tests.test_foo.MyClass')`
- Good: `patch('src.mymodule.MyClass')`

For optional deps like `sentry_sdk`, use `patch.dict('sys.modules', {'sentry_sdk': mock, 'sentry_sdk.integrations': mock})`; patch sub-modules explicitly to prevent import leaks.

**Why:** Usage-site patches intercept only that one import; other callers and subsequent imports still see the real object, producing inconsistent test behavior.
