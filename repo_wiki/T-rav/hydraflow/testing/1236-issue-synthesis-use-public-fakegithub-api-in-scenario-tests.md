---
id: 1236
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T20:11:03.006338+00:00
status: active
corroborations: 1
supersedes: 1162
---

# Use public FakeGitHub API in scenario tests

Always use the public API to mutate FakeGitHub state in scenario tests; never write to private attributes directly.

Example: Bad: `world.github._issues[901].state = "closed"`. Good: `await world.github.close_issue(901)`.

**Why:** If FakeIssue internals change, direct attribute writes silently remain valid Python while the fake's behavior drifts — the public API is the compatibility boundary.
