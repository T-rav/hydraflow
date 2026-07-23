---
id: 0451
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:41:04.337698+00:00
status: superseded
corroborations: 1
supersedes: 0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445,0446,0447,0448,0449,0450
superseded_by: 0492
---

# Mock at definition site, not at usage site

Patch symbols at the module where they are defined, not where they are imported.

Example: Good: `patch('src.foo._cache')`. Bad: `patch('src.consumer._cache')`. For optional deps: `patch.dict("sys.modules", {"sentry_sdk": mock_sdk})`.

**Why:** Usage-site patches intercept only one import; other callers see the real object, producing inconsistent test behavior.
