---
id: 0063
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T14:41:04.269004+00:00
status: superseded
corroborations: 1
supersedes: 0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062
superseded_by: 0093
---

# Mock at definition site, not at the import site

Patch symbols at the module where they are defined, not where they are imported.

- Bad: `patch('tests.test_foo.MyClass')`
- Good: `patch('src.mymodule.MyClass')`

For optional deps like `sentry_sdk`, use `patch.dict('sys.modules', {'sentry_sdk': mock, 'sentry_sdk.integrations': mock})`; patch sub-modules explicitly to prevent import leaks.

**Why:** Usage-site patches intercept only that one import; other callers and subsequent imports still see the real object, producing inconsistent test behavior.
