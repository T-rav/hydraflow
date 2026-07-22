---
id: 0539
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T15:34:08.393614+00:00
status: active
corroborations: 1
supersedes: 0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530
---

# Use public FakeGitHub API in scenario tests

Always use the public API to mutate `FakeGitHub` state in scenario tests; never write to private attributes directly.

Example: Bad: `world.github._issues[901].state = "closed"`. Good: `await world.github.close_issue(901)`.

**Why:** If `FakeIssue` internals change, direct attribute writes silently remain valid Python while the fake's behavior drifts — the public API is the compatibility boundary.
