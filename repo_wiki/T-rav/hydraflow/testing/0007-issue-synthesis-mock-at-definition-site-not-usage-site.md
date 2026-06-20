---
id: 0007
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.826932+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
superseded_by: 0034
---

# Mock at definition site, not usage site

Patch symbols at the module where they are defined, not where they are imported.

- Bad: `patch("tests.test_foo.MyClass")`
- Good: `patch("src.mymodule.MyClass")`

For optional dependencies like `sentry_sdk`, use `patch.dict("sys.modules", {"sentry_sdk": mock, "sentry_sdk.integrations": mock})` to guarantee cleanup across all tests in the session.

**Why:** Usage-site patches intercept only that one import; other callers and subsequent imports still see the real object, producing inconsistent test behavior.
