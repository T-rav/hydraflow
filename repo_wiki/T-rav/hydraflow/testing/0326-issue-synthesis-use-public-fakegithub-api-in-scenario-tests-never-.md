---
id: 0326
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:38:53.896208+00:00
status: active
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
---

# Use public FakeGitHub API in scenario tests, never mutate _issues

Always use the public API to mutate `FakeGitHub` state in scenario tests; never write to private attributes directly.

- Bad: `world.github._issues[901].state = "closed"`
- Good: `await world.github.close_issue(901)`

**Why:** If `FakeIssue` internals change, direct attribute writes silently remain valid Python while the fake's behavior drifts — the public API is the compatibility boundary that signals breakage.
