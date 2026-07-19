---
id: 0373
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:49:52.715837+00:00
status: superseded
corroborations: 1
supersedes: 0334,0335,0336,0337,0338,0339,0340,0341,0342,0343,0344,0345,0346,0347,0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369,0370,0371,0372
superseded_by: 0412
---

# Mock at definition site, not at usage site

Patch symbols at the module where they are defined, not where they are imported.

Example: Good: `patch('src.foo._cache')`. Bad: `patch('src.consumer._cache')`. For optional deps: `patch.dict("sys.modules", {"sentry_sdk": mock_sdk})`.

**Why:** Usage-site patches intercept only one import; other callers see the real object, producing inconsistent test behavior.
