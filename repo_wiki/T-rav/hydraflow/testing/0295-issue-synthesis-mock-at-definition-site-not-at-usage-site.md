---
id: 0295
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:38:53.876326+00:00
status: active
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
---

# Mock at definition site, not at usage site

Patch symbols at the module where they are *defined*, not where they are imported.

- Good: `patch('src.foo._cache')`
- Bad: `patch('src.consumer._cache')`

For optional deps like `sentry_sdk`, use `patch.dict("sys.modules", {"sentry_sdk": mock_sdk, "sentry_sdk.integrations": mock_int})`.

**Why:** Usage-site patches intercept only one import; other callers and subsequent imports still see the real object, producing inconsistent test behavior.
