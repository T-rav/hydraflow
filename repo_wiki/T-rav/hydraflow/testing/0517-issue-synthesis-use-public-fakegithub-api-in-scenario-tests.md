---
id: 0517
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T12:10:40.689022+00:00
status: active
corroborations: 1
supersedes: 0500,0501,0502,0503,0504,0505,0506,0507,0508,0509
---

# Use public FakeGitHub API in scenario tests

Always use the public API to mutate `FakeGitHub` state in scenario tests; never write to private attributes directly.

Example: Bad: `world.github._issues[901].state = "closed"`. Good: `await world.github.close_issue(901)`

**Why:** If `FakeIssue` internals change, direct attribute writes silently remain valid Python while the fake's behavior drifts — the public API is the compatibility boundary.
