---
id: 1023
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.441658+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# Use public FakeGitHub API in scenario tests

Always use the public API to mutate FakeGitHub state in scenario tests; never write to private attributes directly.

Example: Bad: world.github._issues[901].state = "closed". Good: await world.github.close_issue(901).

**Why:** If FakeIssue internals change, direct attribute writes silently remain valid Python while the fake's behavior drifts — the public API is the compatibility boundary.
