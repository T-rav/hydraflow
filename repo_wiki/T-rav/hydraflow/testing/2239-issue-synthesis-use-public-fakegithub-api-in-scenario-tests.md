---
id: 2239
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:36.808275+00:00
status: superseded
corroborations: 1
supersedes: 2094
superseded_by: 2429
---

# Use public FakeGitHub API in scenario tests

Always use the public API to mutate FakeGitHub state in scenario tests; never write to private attributes directly.

Example: Bad: `world.github._issues[901].state = 'closed'`. Good: `await world.github.close_issue(901)`.

**Why:** If FakeIssue internals change, direct attribute writes silently remain valid Python while the fake's behavior drifts — the public API is the compatibility boundary.
