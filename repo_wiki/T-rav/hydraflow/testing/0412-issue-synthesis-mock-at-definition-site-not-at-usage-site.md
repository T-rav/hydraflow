---
id: 0412
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:46:15.844289+00:00
status: active
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401,0402,0403,0404,0405,0406,0407,0408,0409,0410,0411
---

# Mock at definition site, not at usage site

Patch symbols at the module where they are defined, not where they are imported.

Example: Good: `patch('src.foo._cache')`. Bad: `patch('src.consumer._cache')`. For optional deps: `patch.dict("sys.modules", {"sentry_sdk": mock_sdk})`.

**Why:** Usage-site patches intercept only one import; other callers see the real object, producing inconsistent test behavior.
