---
id: 0007
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.408197+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Mock at definition site, not at usage site

Patch at the module where the target is *defined*, not where it is imported.

- Good: `patch('src.foo._cache')`
- Bad: `patch('src.consumer._cache')`

For optional libraries, use `patch.dict("sys.modules", {"sentry_sdk": mock_sdk, "sentry_sdk.integrations": mock_int})` to guarantee teardown after the test.

**Why:** Patching at the usage site leaves the original binding intact; the real object runs despite the mock.
