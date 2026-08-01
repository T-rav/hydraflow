---
id: 2094
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.188585+00:00
status: superseded
corroborations: 1
supersedes: 1964
superseded_by: 2239
---

# Use public FakeGitHub API in scenario tests

Always use the public API to mutate FakeGitHub state in scenario tests; never write to private attributes directly.

Example: Bad: `world.github._issues[901].state = 'closed'`. Good: `await world.github.close_issue(901)`.

**Why:** If FakeIssue internals change, direct attribute writes silently remain valid Python while the fake's behavior drifts — the public API is the compatibility boundary.
